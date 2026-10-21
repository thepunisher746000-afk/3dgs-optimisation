#!/usr/bin/env python3
"""Analyse statistique d'un modèle 3DGS (PLY / .splat / .gsq).

Donne le « profil » de la scène avant optimisation : nombre de gaussiennes, poids par attribut,
distributions d'opacité et de taille, étendue spatiale, et nombre de candidats à la suppression
pour chaque critère de nettoyage. Sert à choisir les seuils de clean.py / prune.py.

    python3 scripts/analyze.py scene.ply [--json stats.json] [--plot histos.png]
"""
import argparse
import json
import os
import sys

import numpy as np

from gsply import load, human_size


def quantiles(x, qs=(0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)):
    return {f"p{int(q * 100):02d}": float(np.quantile(x, q)) for q in qs}


def analyze(g, path=None):
    N = len(g)
    finite = np.isfinite(g.xyz).all(1) & np.isfinite(g.scale).all(1) & np.isfinite(g.opacity)
    g = g.subset(finite) if not finite.all() else g
    a = g.alpha
    s = g.sigma
    smax, smin = s.max(1), s.min(1)
    center = np.median(g.xyz, 0)
    dist = np.linalg.norm(g.xyz - center, axis=1)
    K = g.f_rest.shape[2]
    sh_energy = np.linalg.norm(g.f_rest.reshape(len(g), -1), axis=1) if K else np.zeros(len(g))
    dc_energy = np.linalg.norm(g.f_dc, axis=1)

    floats = 3 + 3 + 3 * K + 1 + 3 + 4
    st = {
        "file": path,
        "file_size": os.path.getsize(path) if path and os.path.exists(path) else None,
        "n_gaussians": N,
        "n_non_finite": int(N - finite.sum()),
        "sh_degree": g.sh_degree,
        "bytes_per_gaussian_float32": floats * 4,
        "share_of_sh_rest_in_params": 3 * K / floats,
        "bbox_min": g.xyz.min(0).tolist(),
        "bbox_max": g.xyz.max(0).tolist(),
        "robust_center": center.tolist(),
        "dist_to_center": quantiles(dist),
        "alpha": quantiles(a),
        "sigma_max": quantiles(smax),
        "anisotropy_max_over_min": quantiles(smax / np.maximum(smin, 1e-12)),
        "sh_rest_energy_over_dc": quantiles(sh_energy / np.maximum(dc_energy, 1e-6)) if K else None,
        "candidates": {
            "alpha<1/255": int((a < 1 / 255).sum()),
            "alpha<0.01": int((a < 0.01).sum()),
            "alpha<0.05": int((a < 0.05).sum()),
            "sigma_max>20*median": int((smax > 20 * np.median(smax)).sum()),
            "sigma_max>50*median": int((smax > 50 * np.median(smax)).sum()),
            "dist>2*p95": int((dist > 2 * np.quantile(dist, 0.95)).sum()),
            "dist>3*p99": int((dist > 3 * np.quantile(dist, 0.99)).sum()),
        },
    }
    return st, (a, smax, dist, sh_energy)


def print_report(st):
    N = st["n_gaussians"]
    print(f"Fichier            : {st['file']}")
    if st["file_size"]:
        print(f"Taille             : {human_size(st['file_size'])} "
              f"({st['file_size'] / max(N, 1):.1f} o/gaussienne)")
    print(f"Gaussiennes        : {N:,}".replace(",", " "))
    print(f"Degré SH           : {st['sh_degree']}  "
          f"(les coefficients SH>0 = {100 * st['share_of_sh_rest_in_params']:.0f}% des paramètres)")
    print(f"Non finies (NaN)   : {st['n_non_finite']}")
    print(f"Boîte englobante   : {np.round(st['bbox_min'], 2)} -> {np.round(st['bbox_max'], 2)}")
    fmt = lambda d: "  ".join(f"{k}={v:.3g}" for k, v in d.items())
    print(f"Opacité alpha      : {fmt(st['alpha'])}")
    print(f"Taille max (sigma) : {fmt(st['sigma_max'])}")
    print(f"Distance au centre : {fmt(st['dist_to_center'])}")
    if st["sh_rest_energy_over_dc"]:
        print(f"|SH rest| / |DC|   : {fmt(st['sh_rest_energy_over_dc'])}")
    print("Candidats à la suppression :")
    for k, v in st["candidates"].items():
        print(f"  {k:<22} {v:>10}  ({100 * v / max(N, 1):5.1f} %)")


def plot(arrays, out):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib absent : pas d'histogrammes", file=sys.stderr)
        return
    a, smax, dist, she = arrays
    fig, ax = plt.subplots(1, 4, figsize=(18, 4))
    ax[0].hist(a, bins=100); ax[0].set_title("Opacité alpha"); ax[0].set_yscale("log")
    ax[1].hist(np.log10(smax + 1e-12), bins=100); ax[1].set_title("log10(sigma max)"); ax[1].set_yscale("log")
    ax[2].hist(np.log10(dist + 1e-12), bins=100); ax[2].set_title("log10(distance au centre)"); ax[2].set_yscale("log")
    ax[3].hist(she, bins=100); ax[3].set_title("Énergie SH (ordres >= 1)"); ax[3].set_yscale("log")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print(f"Histogrammes -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--json", help="écrit les statistiques en JSON")
    ap.add_argument("--plot", help="écrit des histogrammes (PNG, nécessite matplotlib)")
    args = ap.parse_args()
    g = load(args.input)
    st, arrays = analyze(g, args.input)
    print_report(st)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(st, f, indent=2)
    if args.plot:
        plot(arrays, args.plot)


if __name__ == "__main__":
    main()
