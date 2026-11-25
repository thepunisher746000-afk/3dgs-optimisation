#!/usr/bin/env python3
"""Interface web du projet 3DGS.

    python3 app.py              ->  http://localhost:8000
    python3 app.py --port 9000
    python3 app.py --host 0.0.0.0   (accessible depuis le réseau local : à éviter sur un réseau public)

Sert le portail (ui/), la documentation, le visualiseur et les modèles, et lance les scripts
d'optimisation en tâche de fond (journal en direct dans l'interface). Bibliothèque standard uniquement.
"""
import argparse
import json
import os
import re
import shlex
import struct
import subprocess
import sys
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
REAL_ROOT = os.path.realpath(ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import formats  # noqa: E402  (détection des formats, scripts/formats.py)

MODEL_EXT = formats.MODEL_EXT
CAPTURES = os.path.join(ROOT, "data", "captures")
JOBS = {}
JOBS_LOCK = threading.Lock()


# ------------------------------------------------------------------ fichiers
def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def safe_path(relpath, must_exist=True, roots=None):
    p = os.path.realpath(os.path.join(ROOT, relpath))
    if not p.startswith(REAL_ROOT + os.sep):
        raise ValueError("chemin hors du projet")
    if roots and not any(p.startswith(os.path.join(REAL_ROOT, r) + os.sep) for r in roots):
        raise ValueError(f"chemin non autorisé (dossiers permis : {', '.join(roots)})")
    if must_exist and not os.path.exists(p):
        raise ValueError(f"fichier introuvable : {relpath}")
    return p


def safe_detect(p):
    try:
        return formats.detect(p)
    except Exception as e:
        return {"kind": "unknown", "label": f"illisible ({e})", "category": "unknown", "details": {}}


def list_models():
    """Modèles 3DGS de data/ et results/ (hors captures et sorties de benchmark), avec type détecté."""
    out = []
    for base in ("data", "results"):
        for dp, dirs, files in os.walk(os.path.join(ROOT, base)):
            dirs[:] = [d for d in dirs if d not in ("captures", "benchmark")]
            for f in files:
                if f.lower().endswith(MODEL_EXT):
                    p = os.path.join(dp, f)
                    st = os.stat(p)
                    d = safe_detect(p)
                    short = {"gaussians": "PLY 3DGS", "gaussians_compressed": "PLY compressé", "splat": ".splat",
                             "ksplat": ".ksplat", "spz": "SPZ", "sog": "SOG", "gsq": "GSQ", "pointcloud": "nuage de points",
                             "mesh": "maillage"}.get(d["kind"], d["label"])
                    kind = "GSQ décodé" if f.lower().endswith(".gsq.ply") else short
                    out.append({"path": rel(p), "name": f, "dir": rel(dp), "size": st.st_size, "mtime": st.st_mtime,
                                "kind": kind, "type": d["kind"], "category": d["category"],
                                "count": d["details"].get("n"),
                                "usable": d["kind"] in ("gaussians", "splat", "gsq"),
                                "viewable": d["kind"] in ("gaussians", "splat", "ksplat", "spz")})
    out.sort(key=lambda m: -m["mtime"])
    return out


def list_captures():
    """Captures (vidéos, photos) de data/captures/<nom>/ et leur état d'avancement vers un modèle."""
    out = []
    if not os.path.isdir(CAPTURES):
        return out
    for name in sorted(os.listdir(CAPTURES)):
        d = os.path.join(CAPTURES, name)
        if not os.path.isdir(d):
            continue
        videos = []
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(formats.VIDEO_EXT):
                det = safe_detect(os.path.join(d, f))
                videos.append({"name": f, "path": rel(os.path.join(d, f)), "size": os.path.getsize(os.path.join(d, f)),
                               **det["details"]})
        img_dir = os.path.join(d, "images")
        images = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(formats.IMAGE_EXT)) if os.path.isdir(img_dir) else []
        zip_path = os.path.join(d, f"{name}_images.zip")
        model = os.path.join(ROOT, "data", f"{name}.ply")
        check = read_json(os.path.join(d, "check.json"))
        out.append({"name": name, "dir": rel(d), "videos": videos, "images": len(images),
                    "check": {k: check.get(k) for k in ("level", "verdict", "issues", "advice", "images", "linked_pairs",
                                                        "components")} if check else None,
                    "image_sample": [rel(os.path.join(img_dir, f)) for f in images[:: max(1, len(images) // 6)][:6]],
                    "zip": rel(zip_path) if os.path.exists(zip_path) else None,
                    "model": rel(model) if os.path.exists(model) else None,
                    "mtime": os.path.getmtime(d)})
    out.sort(key=lambda c: -c["mtime"])
    return out


def tools_status():
    """Outils externes optionnels détectés (pour activer les actions correspondantes dans l'interface)."""
    import shutil
    try:
        import cv2  # noqa: F401
        cv = True
    except ImportError:
        cv = False
    try:
        import scipy  # noqa: F401
        sp = True
    except ImportError:
        sp = False
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from train_3dgs import available_backends
    return {"opencv": cv, "scipy": sp, "trainers": available_backends(),
            "splat_transform": bool(shutil.which("splat-transform"))}


def read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_results():
    scenes = []
    base = os.path.join(ROOT, "results")
    if not os.path.isdir(base):
        return scenes
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d)
        if not os.path.isdir(p):
            continue
        files = sorted(os.listdir(p))
        scenes.append({
            "name": d,
            "summary": read_json(os.path.join(p, "summary.json")),
            "analyze": read_json(os.path.join(p, "analyze.json")),
            "reports": {f: read_json(os.path.join(p, f)) for f in files if f.endswith("_report.json")},
            "benches": [{"file": f, "data": read_json(os.path.join(p, f))} for f in files
                        if f.startswith("bench_") and f.endswith(".json")],
            "files": [{"name": f, "path": rel(os.path.join(p, f)), "size": os.path.getsize(os.path.join(p, f))}
                      for f in files if f.lower().endswith(MODEL_EXT)],
            "benchmark": read_json(os.path.join(p, "benchmark", "benchmark.json")),
        })
    return scenes


def list_docs():
    docs = [{"file": "README.md", "title": "Présentation du projet"}]
    ddir = os.path.join(ROOT, "docs")
    for f in sorted(os.listdir(ddir)):
        if f.endswith(".md"):
            title = f
            with open(os.path.join(ddir, f), encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            docs.append({"file": "docs/" + f, "title": title})
    return docs


# ------------------------------------------------------------------- tâches
def scene_dir_and_stem(inp):
    """results/<scène>/ pour ranger les sorties à côté de leur scène."""
    name = os.path.basename(inp)
    stem = re.sub(r"(\.gsq)?\.(ply|splat|gsq|ksplat|spz)$", "", name, flags=re.I)
    parts = inp.split("/")
    if len(parts) >= 3 and parts[0] == "results":
        return "/".join(parts[:2]), stem
    return f"results/{stem}", stem


def num(params, key, default, lo=None, hi=None, cast=float):
    v = params.get(key, default)
    if v in (None, ""):
        return None
    v = cast(v)
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ValueError(f"{key} doit être entre {lo} et {hi}")
    return v


def build_command(tool, p):
    """Construit la ligne de commande d'un outil à partir des paramètres du formulaire (liste blanche)."""
    S = lambda s: f"scripts/{s}"
    if tool == "synthetic":
        n = num(p, "n", 200000, 1000, 5_000_000, int)
        out = "data/synthetic.ply"
        return [S("make_synthetic.py"), out, "--n", str(n)], [out]

    if tool in ("frames", "train", "zip", "check"):
        cap = p.get("capture") or ""
        capdir = safe_path(cap, roots=("data",))
        name = os.path.basename(capdir)
        if tool == "frames":
            video = p.get("video") or ""
            safe_path(video, roots=("data",))
            fps = num(p, "fps", 3, 0.2, 30)
            side = num(p, "max_side", 1920, 0, 8000, int)
            return [S("extract_frames.py"), video, f"{cap}/images", "--fps", f"{fps:g}", "--max-side", str(side)], \
                   [f"{cap}/images"]
        if tool == "check":
            return [S("check_capture.py"), cap], [f"{cap}/check.json"]
        if tool == "train":
            it = num(p, "iterations", 7000, 500, 100000, int)
            return [S("train_3dgs.py"), cap, "--iterations", str(it)], [f"data/{name}.ply"]
        return ["-m", "zipfile", "-c", f"{cap}/{name}_images.zip", f"{cap}/images"], [f"{cap}/{name}_images.zip"]

    inp = p.get("input") or ""
    safe_path(inp, roots=("data", "results"))
    outdir, stem = scene_dir_and_stem(inp)
    det = safe_detect(os.path.join(ROOT, inp))
    if tool != "convert" and det["kind"] not in ("gaussians", "splat", "gsq"):
        raise ValueError(f"{det['label']} : ce fichier ne peut pas être traité directement"
                         + (" (le convertir d'abord en PLY)" if det["category"] == "model" else ""))

    if tool == "convert":
        out = f"data/{stem}.ply"
        return ["-c", "import subprocess,sys; sys.exit(subprocess.call(['splat-transform', sys.argv[1], sys.argv[2]]))",
                inp, out], [out]

    if tool == "benchmark":
        suite = p.get("suite", "configs/benchmark.json")
        safe_path(suite, roots=("configs",))
        args = [S("benchmark.py"), inp, "--suite", suite, "--views", str(num(p, "views", 6, 1, 32, int)),
                "--out", f"{outdir}/benchmark"]
        if p.get("only"):
            args += ["--only"] + [s for s in p["only"] if re.fullmatch(r"[\w ()éèàç\-]+", s)]
        return args, [f"{outdir}/benchmark/benchmark.md"]

    if tool == "analyze":
        return [S("analyze.py"), inp, "--json", f"{outdir}/analyze.json"], [f"{outdir}/analyze.json"]

    if tool == "clean":
        preset = p.get("preset", "medium")
        if preset not in ("light", "medium", "aggressive", "custom"):
            raise ValueError("préréglage inconnu")
        out = f"{outdir}/{stem}_clean_{preset}.ply"
        args = [S("clean.py"), inp, out, "--report", f"{outdir}/{stem}_clean_{preset}_report.json"]
        if preset != "custom":
            args += ["--preset", preset]
        if p.get("min_opacity") not in (None, ""):
            args += ["--min-opacity", str(num(p, "min_opacity", None, 0, 1))]
        if p.get("floaters"):
            args += ["--floaters", str(num(p, "floater_alpha", 0.2, 0, 1)), str(num(p, "floater_mult", 5, 1, 1000))]
        if p.get("max_scale_mult") not in (None, ""):
            args += ["--max-scale-mult", str(num(p, "max_scale_mult", None, 1, 1e6))]
        if p.get("auto_crop"):
            args += ["--auto-crop", str(num(p, "crop_q", 0.99, 0.5, 1)), str(num(p, "crop_factor", 2, 1, 100))]
        if p.get("sor"):
            args += ["--sor", "16", str(num(p, "sor_sigma", 2.0, 0.5, 10))]
        return args, [out]

    if tool == "prune":
        ratio = num(p, "keep_ratio", 0.75, 0.01, 1)
        score = p.get("score", "orbit")
        out = f"{outdir}/{stem}_prune{int(round(ratio * 100))}_{score}.ply"
        args = [S("prune.py"), inp, out, "--keep-ratio", f"{ratio:g}"]
        if score == "orbit":
            args += ["--orbit", str(num(p, "orbit_n", 32, 4, 256, int))]
        elif score == "cameras":
            cams = p.get("cameras", "")
            safe_path(cams)
            args += ["--cameras", cams]
        elif score != "proxy":
            raise ValueError("score inconnu")
        if score != "proxy" and p.get("occlusion", True):
            args += ["--occlusion"]
        args += ["--min-coverage", f"{num(p, 'min_coverage', 0.25, 0, 1) or 0:g}"]
        if p.get("compensate", True):
            args += ["--compensate"]
        return args, [out]

    if tool == "sh":
        deg = num(p, "degree", 1, 0, 3, int)
        out = f"{outdir}/{stem}_sh{deg}.ply"
        args = [S("sh_reduce.py"), inp, out, "--degree", str(deg)]
        if p.get("adaptive") not in (None, "", 0, "0"):
            args += ["--adaptive", str(num(p, "adaptive", 0.05, 0, 1))]
        return args, [out]

    if tool == "gsq":
        sh = p.get("sh", "vq")
        if sh not in ("none", "8bit", "vq"):
            raise ValueError("mode SH inconnu")
        out = f"{outdir}/{stem}_{sh}.gsq"
        args = [S("gsq.py"), "encode", inp, out, "--sh", sh, "--decoded", out + ".ply",
                "--pos", "11-10-11" if p.get("pos") == "11-10-11" else "16"]
        if sh == "vq":
            args += ["--codebook", str(num(p, "codebook", 4096, 16, 65536, int))]
            if p.get("sh_zero") not in (None, "", 0, "0"):
                args += ["--sh-zero", str(num(p, "sh_zero", 0.05, 0, 1))]
        return args, [out, out + ".ply"]

    if tool == "pipeline":
        cfg = p.get("config", "configs/default.json")
        safe_path(cfg, roots=("configs",))
        args = [S("pipeline.py"), inp, "--out", outdir, "--config", cfg]
        if p.get("gzip"):
            args += ["--gzip"]
        return args, [f"{outdir}/summary.md"]

    raise ValueError(f"outil inconnu : {tool}")


TOOL_TITLES = {"synthetic": "Scène de test", "analyze": "Analyse", "clean": "Nettoyage", "prune": "Élagage",
               "sh": "Réduction SH", "gsq": "Compression GSQ", "pipeline": "Pipeline complet",
               "frames": "Extraction des images", "train": "Génération du modèle", "zip": "Archive des photos",
               "check": "Vérification de la capture",
               "convert": "Conversion en PLY", "benchmark": "Benchmark"}


def store_upload(name, rfile, length, group=None):
    """Enregistre un fichier importé au bon endroit selon son type détecté.
    Modèle -> data/ ; vidéo -> data/captures/<nom>/ ; photo -> data/captures/<groupe>/images/ ;
    archive de photos -> extraite dans data/captures/<nom>/images/."""
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    tmp = os.path.join(ROOT, "data", f".upload_{uuid.uuid4().hex}")
    remaining = length
    with open(tmp, "wb") as f:
        while remaining > 0:
            chunk = rfile.read(min(1 << 20, remaining))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)
    try:
        det = formats.detect(tmp)
        stem = formats.safe_stem(name)
        kind = det["kind"]
        if det["category"] == "model":
            dest = os.path.join(ROOT, "data", name)
            os.replace(tmp, dest)
        elif kind == "video":
            d = os.path.join(CAPTURES, stem)
            os.makedirs(d, exist_ok=True)
            dest = os.path.join(d, name)
            os.replace(tmp, dest)
            det = formats.detect(dest)  # infos vidéo (durée, résolution) une fois le fichier en place
        elif kind == "image":
            g = formats.safe_stem(group or "photos")
            d = os.path.join(CAPTURES, g, "images")
            os.makedirs(d, exist_ok=True)
            dest = os.path.join(d, name)
            os.replace(tmp, dest)
        elif kind == "image_archive":
            import zipfile
            d = os.path.join(CAPTURES, stem, "images")
            os.makedirs(d, exist_ok=True)
            n = 0
            with zipfile.ZipFile(tmp) as z:
                for info in z.infolist():
                    base = os.path.basename(info.filename)
                    if base and not base.startswith(".") and base.lower().endswith(formats.IMAGE_EXT):
                        with z.open(info) as src, open(os.path.join(d, base), "wb") as out:  # nom aplati : pas de ../
                            out.write(src.read())
                        n += 1
            os.remove(tmp)
            dest = d
            det["details"]["extracted"] = n
        else:
            os.remove(tmp)
            raise ValueError(f"{det['label']} : type non pris en charge. Formats acceptés : modèles 3DGS "
                             "(.ply, .splat, .ksplat, .spz, .sog), vidéos (.mp4, .mov…), photos (.jpg, .png…) ou .zip de photos.")
        return {"path": rel(dest), "detected": det}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def start_job(tool, params):
    args, outputs = build_command(tool, params)
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "tool": tool, "title": TOOL_TITLES.get(tool, tool), "input": params.get("input"),
           "cmd": "python3 " + " ".join(shlex.quote(a) for a in args), "status": "running",
           "log": [], "start": time.time(), "end": None, "outputs": outputs, "returncode": None}
    with JOBS_LOCK:
        JOBS[jid] = job

    def run():
        try:
            proc = subprocess.Popen([sys.executable, "-u"] + args, cwd=ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    env=dict(os.environ, PYTHONUNBUFFERED="1"))
            for line in proc.stdout:
                job["log"].append(line.rstrip("\n"))
            proc.wait()
            job["returncode"] = proc.returncode
            job["status"] = "done" if proc.returncode == 0 else "error"
        except Exception as e:  # pragma: no cover
            job["log"].append(f"Erreur : {e}")
            job["status"] = "error"
        job["end"] = time.time()
        job["outputs"] = [o for o in job["outputs"] if os.path.exists(os.path.join(ROOT, o))]

    threading.Thread(target=run, daemon=True).start()
    return job


def job_public(j, since=0):
    d = {k: v for k, v in j.items() if k != "log"}
    d["log"] = j["log"][since:]
    d["log_len"] = len(j["log"])
    return d


# ------------------------------------------------------------------ serveur
class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".md": "text/markdown; charset=utf-8",
                      ".js": "text/javascript", ".json": "application/json", ".ply": "application/octet-stream",
                      ".splat": "application/octet-stream", ".gsq": "application/octet-stream"}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        if "/api/jobs/" not in (args[0] if args else ""):
            sys.stderr.write("  %s\n" % (fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    # ---- GET
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/ui/")
            self.end_headers()
            return
        if not u.path.startswith("/api/"):
            return super().do_GET()
        q = parse_qs(u.query)
        try:
            if u.path == "/api/health":
                return self.send_json({"ok": True, "python": sys.version.split()[0], "root": ROOT})
            if u.path == "/api/models":
                return self.send_json(list_models())
            if u.path == "/api/results":
                return self.send_json(list_results())
            if u.path == "/api/docs":
                return self.send_json(list_docs())
            if u.path == "/api/configs":
                return self.send_json(sorted("configs/" + f for f in os.listdir(os.path.join(ROOT, "configs"))
                                             if f.endswith(".json") and not f.startswith("benchmark")))
            if u.path == "/api/suites":
                return self.send_json(sorted("configs/" + f for f in os.listdir(os.path.join(ROOT, "configs"))
                                             if f.startswith("benchmark") and f.endswith(".json")))
            if u.path == "/api/captures":
                return self.send_json(list_captures())
            if u.path == "/api/tools":
                return self.send_json(tools_status())
            if u.path == "/api/jobs":
                with JOBS_LOCK:
                    jobs = sorted(JOBS.values(), key=lambda j: -j["start"])
                return self.send_json([job_public(j, len(j["log"])) for j in jobs])
            m = re.fullmatch(r"/api/jobs/(\w+)", u.path)
            if m and m.group(1) in JOBS:
                return self.send_json(job_public(JOBS[m.group(1)], int(q.get("since", ["0"])[0])))
            return self.send_json({"error": "introuvable"}, 404)
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)

    # ---- POST
    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/run":
                body = json.loads(self.read_body() or b"{}")
                if body.get("dry"):
                    args, outputs = build_command(body["tool"], body.get("params", {}))
                    return self.send_json({"cmd": "python3 " + " ".join(shlex.quote(a) for a in args),
                                           "outputs": outputs})
                return self.send_json(job_public(start_job(body["tool"], body.get("params", {}))))

            if u.path == "/api/upload":
                name = os.path.basename(q.get("name", [""])[0])
                if not re.fullmatch(r"[\w.\- ()]+", name) or not name.lower().endswith(formats.UPLOAD_EXT):
                    raise ValueError("Type de fichier non accepté. Formats : modèles 3DGS (.ply .splat .ksplat .spz .sog .gsq), "
                                     "vidéos (.mp4 .mov .m4v .avi .mkv .webm), photos (.jpg .png .heic .tif .webp) ou .zip de photos.")
                return self.send_json(store_upload(name, self.rfile, int(self.headers.get("Content-Length", 0)),
                                                   q.get("group", [None])[0]))

            if u.path == "/api/delete_capture":
                body = json.loads(self.read_body())
                p = safe_path(body["path"], roots=("data/captures",))
                if os.path.dirname(p) != os.path.realpath(CAPTURES):
                    raise ValueError("seul un dossier de capture entier peut être supprimé")
                import shutil
                shutil.rmtree(p)
                return self.send_json({"deleted": body["path"]})

            if u.path == "/api/bench":
                data = json.loads(self.read_body())
                scene = re.sub(r"[^\w\-]", "_", q.get("scene", ["bench"])[0]) or "bench"
                d = os.path.join(ROOT, "results", scene)
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, time.strftime("bench_%Y%m%d_%H%M%S.json"))
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return self.send_json({"path": rel(p)})

            if u.path == "/api/delete":
                body = json.loads(self.read_body())
                p = safe_path(body["path"], roots=("data", "results"))
                if not p.lower().endswith(MODEL_EXT + (".json",)):
                    raise ValueError("seuls les modèles et rapports peuvent être supprimés")
                os.remove(p)
                return self.send_json({"deleted": body["path"]})
            return self.send_json({"error": "introuvable"}, 404)
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print(f"\n  Interface 3DGS prête :  {url}\n  (Ctrl+C pour arrêter)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
