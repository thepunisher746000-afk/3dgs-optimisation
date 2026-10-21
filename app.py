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
MODEL_EXT = (".ply", ".splat", ".gsq", ".ksplat", ".spz")
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


def gaussian_count(path):
    """Nombre de gaussiennes lu sans charger le fichier."""
    try:
        if path.endswith(".splat"):
            return os.path.getsize(path) // 32
        with open(path, "rb") as f:
            head = f.read(65536)
        if path.endswith(".gsq"):
            n = struct.unpack("<I", head[4:8])[0]
            return json.loads(head[8:8 + n])["n"]
        if path.endswith(".ply"):
            m = re.search(rb"element vertex (\d+)", head)
            return int(m.group(1)) if m else None
    except Exception:
        return None
    return None


def model_kind(name):
    n = name.lower()
    if n.endswith(".gsq.ply"):
        return "gsq décodé"
    return n.rsplit(".", 1)[-1]


def list_models():
    out = []
    for base in ("data", "results"):
        for dp, _, files in os.walk(os.path.join(ROOT, base)):
            for f in files:
                if f.lower().endswith(MODEL_EXT):
                    p = os.path.join(dp, f)
                    st = os.stat(p)
                    out.append({"path": rel(p), "name": f, "dir": rel(dp), "size": st.st_size,
                                "mtime": st.st_mtime, "kind": model_kind(f), "count": gaussian_count(p),
                                "viewable": not f.lower().endswith(".gsq")})
    out.sort(key=lambda m: -m["mtime"])
    return out


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

    inp = p.get("input") or ""
    safe_path(inp, roots=("data", "results"))
    outdir, stem = scene_dir_and_stem(inp)

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
               "sh": "Réduction SH", "gsq": "Compression GSQ", "pipeline": "Pipeline complet"}


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
                                             if f.endswith(".json")))
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
                if not re.fullmatch(r"[\w.\- ]+", name) or not name.lower().endswith(MODEL_EXT):
                    raise ValueError("nom de fichier invalide (extensions : .ply .splat .gsq .ksplat .spz)")
                os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
                dest = os.path.join(ROOT, "data", name)
                remaining = int(self.headers.get("Content-Length", 0))
                with open(dest, "wb") as f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
                return self.send_json({"path": rel(dest), "size": os.path.getsize(dest)})

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
