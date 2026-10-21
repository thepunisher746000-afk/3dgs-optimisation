#!/usr/bin/env python3
"""Banc d'essai hors-ligne : applique une série de configurations d'optimisation à une scène et
produit, pour chacune, les fichiers à charger dans le visualiseur + un tableau comparatif.

    python3 scripts/pipeline.py scene.ply --out results/scene
    python3 scripts/pipeline.py scene.ply --out results/scene --config configs/default.json --gzip

Chaque configuration est une liste d'étapes (voir configs/default.json) :
    {"clean": {...params de clean.clean()...}}
    {"prune": {"keep_ratio": 0.5, "cameras": "...", "orbit": 32, "occlusion": true}}
    {"sh": {"degree": 1}}            ou {"sh": {"adaptive": 0.05}}
    {"export": ["ply", "splat", "gsq"]}   + options gsq : {"gsq": {"sh": "vq", "codebook": 4096}}

Sorties : <out>/<config>.ply|.splat|.gsq (+ <config>.gsq.ply = version décodée, visualisable),
          <out>/summary.csv, <out>/summary.md, <out>/summary.json
"""
import argparse
import csv
import gzip
import json
import os
import time

import numpy as np

import clean as C
import gsq as Q
import prune as P
import sh_reduce as S
from gsply import load, write_ply, write_splat, human_size

DEFAULT_CONFIGS = [
    {"name": "C0_original", "steps": [{"export": ["ply"]}]},
    {"name": "C1_clean_light", "steps": [{"clean": {"preset": "light"}}, {"export": ["ply", "splat"]}]},
    {"name": "C2_clean_medium", "steps": [{"clean": {"preset": "medium"}}, {"export": ["ply", "splat"]}]},
    {"name": "C3_prune50", "steps": [{"clean": {"preset": "medium"}}, {"prune": {"keep_ratio": 0.5}},
                                     {"export": ["ply", "splat"]}]},
    {"name": "C4_prune50_sh1", "steps": [{"clean": {"preset": "medium"}}, {"prune": {"keep_ratio": 0.5}},
                                         {"sh": {"degree": 1}}, {"export": ["ply"]}]},
    {"name": "C5_prune50_gsq_vq", "steps": [{"clean": {"preset": "medium"}}, {"prune": {"keep_ratio": 0.5}},
                                            {"export": ["gsq"]}, {"gsq": {"sh": "vq", "codebook": 4096}}]},
    {"name": "C6_prune30_sh1_gsq", "steps": [{"clean": {"preset": "medium"}}, {"prune": {"keep_ratio": 0.3}},
                                             {"sh": {"degree": 1}}, {"export": ["gsq", "splat"]},
                                             {"gsq": {"sh": "8bit"}}]},
]


def gz_size(path):
    with open(path, "rb") as f:
        return len(gzip.compress(f.read(), 6))


def run_config(g0, cfg, out_dir, ref_size, do_gzip, cams_cache):
    g, t0, info = g0, time.time(), {"config": cfg["name"]}
    exports, gsq_opts = ["ply"], {}
    for st in cfg["steps"]:
        (kind, prm), = st.items()
        if kind == "clean":
            prm = dict(prm)
            preset = C.PRESETS.get(prm.pop("preset", None), {})
            g, _ = C.clean(g, **{**preset, **prm}, verbose=False)
        elif kind == "prune":
            g = g.subset(C.mask_finite(g))
            if prm.get("cameras") or prm.get("orbit"):
                key = (prm.get("cameras"), prm.get("orbit"))
                if key not in cams_cache:
                    cams_cache[key] = (P.load_cameras(prm["cameras"]) if prm.get("cameras")
                                       else P.orbit_cameras(g.xyz, prm["orbit"]))
                score = P.importance_views(g, cams_cache[key], occlusion=prm.get("occlusion", False))
            else:
                score = P.importance_proxy(g, prm.get("beta", 0.1))
            g = g.subset(P.select(score, prm.get("keep_ratio"), prm.get("min_score")))
        elif kind == "sh":
            if "degree" in prm:
                g = S.truncate_sh(g, prm["degree"])
            if "adaptive" in prm:
                g, _ = S.adaptive_zero_sh(g, prm["adaptive"])
        elif kind == "export":
            exports = prm
        elif kind == "gsq":
            gsq_opts = prm
        else:
            raise ValueError(f"étape inconnue : {kind}")
    info["process_s"] = round(time.time() - t0, 2)
    info["n_gaussians"] = len(g)
    info["n_ratio"] = round(len(g) / len(g0), 4)
    info["sh_degree"] = g.sh_degree

    base = os.path.join(out_dir, cfg["name"])
    for fmt in exports:
        if fmt == "ply":
            write_ply(base + ".ply", g)
        elif fmt == "splat":
            write_splat(base + ".splat", g)
        elif fmt == "gsq":
            blob, ref, st = Q.encode(g, gsq_opts.get("pos", "16"), gsq_opts.get("sh", "vq"),
                                     gsq_opts.get("codebook", 4096), gsq_opts.get("sh_zero", 0.0),
                                     gsq_opts.get("entropy", "lzma"), verbose=False)
            with open(base + ".gsq", "wb") as f:
                f.write(blob)
            dec = Q.decode(blob)
            write_ply(base + ".gsq.ply", dec)  # pour la mesure de qualité dans le visualiseur
            info.update({f"gsq_{k}": float(f"{v:.4g}") for k, v in Q.reconstruction_errors(ref, dec).items()})
        path = base + "." + fmt
        size = os.path.getsize(path)
        info[f"{fmt}_bytes"] = size
        info[f"{fmt}_ratio"] = round(ref_size / size, 2)
        info[f"{fmt}_B_per_g"] = round(size / max(len(g), 1), 2)
        if do_gzip and fmt != "gsq":
            info[f"{fmt}_gzip_bytes"] = gz_size(path)
    return info


def write_tables(rows, out_dir):
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k != "config", k))
    with open(os.path.join(out_dir, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(rows, f, indent=2)
    cols = [("config", "Config"), ("n_gaussians", "Gaussiennes"), ("sh_degree", "SH"),
            ("ply_bytes", "PLY"), ("ply_ratio", "x PLY"), ("splat_bytes", ".splat"),
            ("gsq_bytes", ".gsq"), ("gsq_ratio", "x gsq"), ("process_s", "Temps (s)")]
    lines = ["| " + " | ".join(c[1] for c in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for k, _ in cols:
            v = r.get(k, "")
            cells.append(human_size(v) if k.endswith("_bytes") and v != "" else
                         (f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)))
        lines.append("| " + " | ".join(cells) + " |")
    md = "\n".join(lines)
    with open(os.path.join(out_dir, "summary.md"), "w") as f:
        f.write(md + "\n")
    print(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", help="fichier JSON de configurations (sinon : configurations par défaut)")
    ap.add_argument("--only", nargs="*", help="noms de configurations à exécuter")
    ap.add_argument("--gzip", action="store_true", help="mesure aussi la taille après gzip (transfert HTTP)")
    args = ap.parse_args()

    configs = json.load(open(args.config)) if args.config else DEFAULT_CONFIGS
    if args.only:
        configs = [c for c in configs if c["name"] in args.only]
    os.makedirs(args.out, exist_ok=True)
    g0 = load(args.input)
    ref_size = os.path.getsize(args.input)
    print(f"Scène : {args.input} — {len(g0):,} gaussiennes, {human_size(ref_size)}\n".replace(",", " "))
    rows, cams = [], {}
    for cfg in configs:
        print(f"> {cfg['name']}")
        rows.append(run_config(g0, cfg, args.out, ref_size, args.gzip, cams))
    print()
    write_tables(rows, args.out)


if __name__ == "__main__":
    main()
