#!/usr/bin/env python3
"""Réduction des harmoniques sphériques (SH) — voir docs/03_optimisation.md, §4.

En degré 3, les coefficients SH d'ordre >= 1 représentent 45 des 59 flottants utiles d'une gaussienne
(~76 % du fichier). Ils ne codent que la variation de couleur avec le point de vue (reflets, brillance).

  * troncature  : on garde les ordres <= d (d=0 : couleur constante, d=1 : 9 coef./canal ... )
  * adaptatif   : on met à zéro les SH d'ordre >= 1 des gaussiennes dont l'énergie relative
                  ||f_rest|| / ||f_dc|| est faible (elles sont quasi diffuses). Le fichier PLY ne
                  rétrécit pas, mais les zéros se compressent très bien (gsq, gzip, SOG...).

    python3 scripts/sh_reduce.py in.ply out.ply --degree 1
    python3 scripts/sh_reduce.py in.ply out.ply --adaptive 0.05
"""
import argparse
import os

import numpy as np

from gsply import load, write_ply, human_size, SH_REST_PER_DEGREE


def truncate_sh(g, degree):
    if degree >= g.sh_degree:
        return g
    g = g.copy()
    g.f_rest = np.ascontiguousarray(g.f_rest[:, :, :SH_REST_PER_DEGREE[degree]])
    return g


def sh_relative_energy(g):
    N = len(g)
    if g.f_rest.shape[2] == 0:
        return np.zeros(N)
    return np.linalg.norm(g.f_rest.reshape(N, -1), axis=1) / np.maximum(np.linalg.norm(g.f_dc, axis=1), 1e-6)


def adaptive_zero_sh(g, threshold):
    """Met à zéro les SH « inutiles ». Retourne (nuage, fraction mise à zéro)."""
    e = sh_relative_energy(g)
    z = e < threshold
    g = g.copy()
    g.f_rest = g.f_rest.copy()
    g.f_rest[z] = 0.0
    return g, float(z.mean())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--degree", type=int, choices=(0, 1, 2, 3))
    ap.add_argument("--adaptive", type=float, metavar="SEUIL", help="seuil d'énergie relative (ex. 0.05)")
    args = ap.parse_args()
    g = load(args.input)
    d0 = g.sh_degree
    if args.degree is not None:
        g = truncate_sh(g, args.degree)
    if args.adaptive:
        g, frac = adaptive_zero_sh(g, args.adaptive)
        print(f"SH mis à zéro pour {100 * frac:.1f} % des gaussiennes")
    write_ply(args.output, g)
    print(f"Degré SH {d0} -> {g.sh_degree} ; {human_size(os.path.getsize(args.input))} -> "
          f"{human_size(os.path.getsize(args.output))}")


if __name__ == "__main__":
    main()
