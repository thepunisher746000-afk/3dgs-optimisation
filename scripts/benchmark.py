#!/usr/bin/env python3
"""Benchmark des algorithmes d'optimisation : lesquels sont les plus utiles ?

Pour chaque variante d'une « suite » (configs/benchmark.json) : on applique les étapes, on exporte au
format demandé, on relit le fichier exporté (donc la perte de compression est incluse) et on le
rend sur CPU (scripts/render.py) depuis des caméras de TEST, distinctes de celles qui servent au
score d'élagage (sinon le score « views » serait évalué sur ses propres vues).

Mesures par variante :
  * taille du fichier, facteur de compression, nombre de gaussiennes, temps de traitement ;
  * qualité par rapport au modèle de référence (par défaut : l'entrée nettoyée) : PSNR et SSIM
    moyens et pire vue ;
  * surdessin (fragments composés par pixel) : indicateur du coût d'affichage, indépendant du GPU.
Puis analyse : front de Pareto taille/qualité, meilleure variante par famille, efficacité
(dB perdus chaque fois que la taille est divisée par 2).

    python3 scripts/benchmark.py data/scene.ply
    python3 scripts/benchmark.py data/scene.ply --suite configs/benchmark.json --views 6 --size 480 360
Sorties : results/<scène>/benchmark/benchmark.json|.csv|.md + img/*.png (vues de comparaison)
"""
import argparse
import csv
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

import gsq as Q
import prune as P
from gsply import load, read_ply, read_splat, write_ply, write_splat, human_size
from metrics_images import psnr, ssim
from pipeline import apply_steps
from render import render, write_png


def eval_cameras(xyz, n, w, h, cameras=None):
    """Caméras de test.
    * avec les poses réelles (cameras.json) : n photos réparties dans la séquence, à la résolution w ;
      c'est le cas normal pour une vraie capture (en intérieur, une orbite extérieure ne voit que les murs) ;
    * sinon : orbite plus proche que celle du score d'élagage, décalée en azimut, deux hauteurs."""
    if cameras:
        cams = P.load_cameras(cameras)
        idx = np.linspace(0, len(cams) - 1, n).round().astype(int)
        out = []
        for i in idx:
            c = cams[i]
            k = w / c.w
            out.append(P.Cam(c.R, c.t, c.fx * k, c.fy * k, c.cx * k, c.cy * k, w, int(round(c.h * k)), c.name))
        return out
    return P.orbit_cameras(xyz, n, w=w, h=h, margin=0.6, elevations=(15.0, 40.0), azimuth0=17.0)


def export(g, fmt, base, opts, tools):
    """Exporte au format demandé et relit le résultat. Retourne (nuage relu, octets, chemin) ou lève."""
    if fmt == "ply":
        write_ply(base + ".ply", g)
        return g, os.path.getsize(base + ".ply"), base + ".ply"
    if fmt == "splat":
        write_splat(base + ".splat", g)
        return read_splat(base + ".splat"), os.path.getsize(base + ".splat"), base + ".splat"
    if fmt == "gsq":
        blob, _, _ = Q.encode(g, opts.get("pos", "16"), opts.get("sh", "vq"), opts.get("codebook", 4096),
                              opts.get("sh_zero", 0.0), opts.get("entropy", "lzma"), verbose=False)
        with open(base + ".gsq", "wb") as f:
            f.write(blob)
        return Q.decode(blob), len(blob), base + ".gsq"
    if fmt.startswith("ext:"):
        name = fmt[4:]
        spec = tools.get(name)
        if not spec:
            raise RuntimeError(f"outil externe « {name} » non décrit dans la suite")
        exe = shutil.which(spec["encode"][0])
        if not exe:
            raise FileNotFoundError(f"{spec['encode'][0]} non installé ({spec.get('install', '')})")
        with tempfile.TemporaryDirectory() as td:
            src, back = os.path.join(td, "in.ply"), os.path.join(td, "back.ply")
            out = base + spec["ext"]
            write_ply(src, g)
            fill = lambda a: [x.format(**{"in": src, "out": out, "back": back}) for x in a]
            for cmd in (spec["encode"], spec["decode"]):
                r = subprocess.run(fill(cmd), capture_output=True, text=True, timeout=1800)
                if r.returncode:
                    raise RuntimeError(f"{' '.join(fill(cmd))} : {r.stderr.strip()[-300:]}")
            return read_ply(back), os.path.getsize(out), out
    raise ValueError(f"format inconnu : {fmt}")


def measure(g, cams, refs):
    ps, ss, od, imgs = [], [], [], []
    for cam, ref in zip(cams, refs):
        img, st = render(g, cam, return_stats=True)
        ps.append(min(50.0, psnr(ref * 255, img * 255)))  # image identique -> PSNR infini, borné à 50 dB
        ss.append(ssim(ref * 255, img * 255))
        od.append(st["overdraw"])
        imgs.append(img)
    return {"psnr": float(np.mean(ps)), "psnr_min": float(min(ps)),
            "ssim": float(np.mean(ss)), "ssim_min": float(min(ss)), "overdraw": float(np.mean(od))}, imgs


def pareto(rows):
    """Variantes non dominées : aucune autre n'est à la fois plus petite et de meilleure qualité."""
    ok = [r for r in rows if r.get("status") == "ok"]
    for r in ok:
        r["pareto"] = not any(o is not r and o["bytes"] <= r["bytes"] and o["psnr"] >= r["psnr"]
                              and (o["bytes"] < r["bytes"] or o["psnr"] > r["psnr"]) for o in ok)


NOT_COMPRESSION = ("Référence", "Nettoyage")  # familles jugées sur le coût d'affichage, pas sur la taille


def analyse(rows, in_bytes, ref_bytes, ref_overdraw, thresholds=(35.0, 30.0)):
    """Synthèse en Markdown. Les gains de taille des familles de compression sont comptés par rapport
    au modèle de RÉFÉRENCE (déjà nettoyé), pour ne pas leur attribuer le gain du nettoyage."""
    ok = [r for r in rows if r.get("status") == "ok"]
    lines = []
    for t in thresholds:
        best = min((r for r in ok if r["psnr"] >= t), key=lambda r: r["bytes"], default=None)
        if best:
            lines.append(f"- **Plus petit fichier avec PSNR ≥ {t:g} dB** : `{best['name']}` — {human_size(best['bytes'])}"
                         f" (×{in_bytes / best['bytes']:.1f} par rapport à l'entrée), {best['psnr']:.1f} dB")
    orig = next((r for r in ok if r["name"] == "original"), None)
    cleans = [r for r in ok if r["family"] in NOT_COMPRESSION and r["name"] != "original"]
    if orig and cleans and ref_overdraw:
        best = min(cleans, key=lambda r: r["overdraw"])
        gain = orig["overdraw"] / max(best["overdraw"], 1e-9)
        verdict = ("c'est lui qui rend l'affichage fluide" if gain >= 2 else
                   "effet modeste sur le coût d'affichage pour cette scène (peu de floaters)")
        lines.append(f"- **Nettoyage** : surdessin {orig['overdraw']:.0f} → {best['overdraw']:.0f} fragments/pixel "
                     f"(÷{gain:.1f}) avec `{best['name']}`, PSNR {best['psnr']:.1f} dB : {verdict}.")
    fams = {}
    for r in ok:
        if r["family"] not in NOT_COMPRESSION:
            fams.setdefault(r["family"], []).append(r)
    lines += ["", "Efficacité de chaque famille (taille comparée au modèle de référence ; PSNR borné à 50 dB = "
              "aucune différence mesurable) :", "",
              "| Famille | Variante la plus efficace | dB perdus par division de la taille par 2 | Gain de taille | PSNR |",
              "|---|---|---|---|---|"]
    for fam, rs in fams.items():
        cand = [r for r in rs if ref_bytes / r["bytes"] > 1.05]
        if not cand:
            continue
        for r in cand:
            r["ratio_ref"] = ref_bytes / r["bytes"]
            r["db_per_halving"] = max(0.0, 50.0 - r["psnr"]) / math.log2(r["ratio_ref"])
        b = min(cand, key=lambda r: (round(r["db_per_halving"], 2), -r["ratio_ref"]))
        lines.append(f"| {fam} | `{b['name']}` | {b['db_per_halving']:.2f} | ×{b['ratio_ref']:.1f} | {b['psnr']:.1f} dB |")
    return "\n".join(lines)


def write_reports(out, scene, env, rows):
    in_bytes = env["input_bytes"]
    ref_bytes = env.get("reference_bytes") or env["reference_n"] * 236  # PLY sans normales, SH degré 3
    pareto(rows)
    summary = analyse(rows, in_bytes, ref_bytes, env.get("reference_overdraw"))
    with open(os.path.join(out, "benchmark.json"), "w", encoding="utf-8") as f:
        json.dump({"env": env, "rows": rows, "summary": summary}, f, indent=1, ensure_ascii=False)
    keys = ["family", "name", "status", "format", "n", "bytes", "ratio", "psnr", "psnr_min", "ssim", "ssim_min",
            "overdraw", "process_s", "pareto", "reason"]
    with open(os.path.join(out, "benchmark.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    md = [f"# Benchmark — {scene}", "", f"{env['date']} · entrée {human_size(in_bytes)} · {env['input_n']:,} gaussiennes · "
          f"{env['views']} vues de test {env['size'][0]}×{env['size'][1]} · durée {env['duration_s']} s".replace(",", " "), "",
          "| Famille | Variante | Taille | Facteur | PSNR (pire) | SSIM | Surdessin | Pareto |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("status") == "ok":
            md.append(f"| {r['family']} | {r['name']} | {human_size(r['bytes'])} | ×{r['ratio']:.1f} | "
                      f"{r['psnr']:.2f} ({r['psnr_min']:.2f}) | {r['ssim']:.4f} | {r['overdraw']:.1f} | {'★' if r.get('pareto') else ''} |")
        else:
            md.append(f"| {r['family']} | {r['name']} | — | — | {r['status']} : {r.get('reason', '')[:80]} | | | |")
    md += ["", "## Analyse", "", summary, ""]
    with open(os.path.join(out, "benchmark.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--suite", default=os.path.join(os.path.dirname(__file__), "..", "configs", "benchmark.json"))
    ap.add_argument("--out", help="dossier de sortie (défaut : results/<scène>/benchmark)")
    ap.add_argument("--views", type=int, default=6)
    ap.add_argument("--size", type=int, nargs=2, default=(400, 300))
    ap.add_argument("--only", nargs="*", help="noms ou familles de variantes à exécuter")
    ap.add_argument("--reanalyse", action="store_true", help="recalcule seulement l'analyse d'un benchmark existant")
    ap.add_argument("--cameras", help="poses réelles pour les vues de test (défaut : data/<scène>_cameras.json s'il existe)")
    args = ap.parse_args()

    if args.reanalyse:
        scene = os.path.basename(args.input).split(".")[0]
        out = args.out or os.path.join("results", scene, "benchmark")
        data = json.load(open(os.path.join(out, "benchmark.json"), encoding="utf-8"))
        print(write_reports(out, scene, data["env"], data["rows"]))
        return

    suite = json.load(open(args.suite, encoding="utf-8"))
    scene = os.path.basename(args.input).split(".")[0]
    out = args.out or os.path.join("results", scene, "benchmark")
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    W, H = args.size

    t0 = time.time()
    g_in = load(args.input)
    in_bytes = os.path.getsize(args.input)
    g_ref, _, _ = apply_steps(g_in, suite.get("reference", []))
    cam_file = args.cameras or next((c for c in (args.input[:-4] + "_cameras.json",) if os.path.exists(c)), None)
    cams = eval_cameras(g_ref.xyz, args.views, W, H, cam_file)
    if cam_file:
        print(f"Vues de test : {len(cams)} poses réelles de {cam_file}")
    print(f"Scène {args.input} : {len(g_in):,} gaussiennes, {human_size(in_bytes)}".replace(",", " "))
    print(f"Référence qualité : {suite.get('reference_label', 'entrée nettoyée')} ({len(g_ref):,} gaussiennes) ;"
          f" {len(cams)} vues de test {W}x{H}".replace(",", " "))
    refs, ref_od = [], []
    for i, cam in enumerate(cams):
        img, st = render(g_ref, cam, return_stats=True)
        refs.append(img); ref_od.append(st["overdraw"])
        write_png(os.path.join(out, "img", f"_reference_{i}.png"), img)

    variants = suite["variants"]
    if args.only:
        variants = [v for v in variants if v["name"] in args.only or v["family"] in args.only]
    rows, cams_cache, tools = [], {}, suite.get("external_tools", {})
    if cam_file:  # poses pour le score d'élagage = toutes sauf celles des vues de test (séparation entraînement/test)
        test_names = {c.name for c in cams}
        cams_cache["scene"] = [c for c in P.load_cameras(cam_file) if c.name not in test_names]
    for k, v in enumerate(variants, 1):
        print(f"[{k}/{len(variants)}] {v['family']} · {v['name']}", flush=True)
        row = {"name": v["name"], "family": v["family"], "label": v.get("label", v["name"]), "format": v["format"]}
        try:
            t = time.time()
            g, _, _ = apply_steps(g_in, v.get("steps", []), cams_cache)
            row["process_s"] = round(time.time() - t, 2)
            ge, nbytes, path = export(g, v["format"], os.path.join(out, v["name"]), v.get("options", {}), tools)
            m, imgs = measure(ge, cams, refs)
            for i, img in enumerate(imgs[:2]):
                write_png(os.path.join(out, "img", f"{v['name']}_{i}.png"), img)
            row.update(m, status="ok", n=len(g), bytes=nbytes, ratio=in_bytes / nbytes, file=path.replace(os.sep, "/"),
                       sh_degree=ge.sh_degree)
            print(f"      {human_size(nbytes):>9}  ×{row['ratio']:<6.1f} PSNR {m['psnr']:5.2f} dB (pire {m['psnr_min']:5.2f})"
                  f"  SSIM {m['ssim']:.4f}  surdessin {m['overdraw']:.1f}", flush=True)
        except FileNotFoundError as e:
            row.update(status="skipped", reason=str(e))
            print(f"      ignorée : {e}")
        except Exception as e:  # une variante qui échoue ne doit pas arrêter le benchmark
            row.update(status="error", reason=str(e))
            print(f"      erreur : {e}")
        rows.append(row)

    env = {"date": time.strftime("%Y-%m-%d %H:%M"), "python": sys.version.split()[0], "machine": platform.platform(),
           "input": args.input, "input_bytes": in_bytes, "input_n": len(g_in), "reference_n": len(g_ref),
           "reference_bytes": len(g_ref) * 4 * g_ref.floats_per_gaussian(),
           "reference_overdraw": float(np.mean(ref_od)), "views": len(cams), "size": [W, H],
           "cameras": cam_file, "view_names": [c.name for c in cams],
           "suite": os.path.relpath(args.suite), "duration_s": round(time.time() - t0, 1)}
    summary = write_reports(out, scene, env, rows)
    print("\n" + summary)
    print(f"\nRésultats : {out}/benchmark.md  ({env['duration_s']} s)")


if __name__ == "__main__":
    main()
