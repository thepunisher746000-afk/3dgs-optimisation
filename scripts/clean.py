#!/usr/bin/env python3
"""Nettoyage d'un modèle 3DGS : suppression des gaussiennes invalides, invisibles ou aberrantes.

Chaque filtre produit un masque booléen « à garder » ; les filtres sont appliqués en cascade
et le nombre de gaussiennes retirées par chacun est journalisé (voir docs/03_optimisation.md, §2).

Filtres disponibles (dans l'ordre d'application) :
  A1  finite          : retire les NaN / Inf
  A2  opacity         : alpha = sigmoid(o) < seuil  -> contribution quasi nulle
  A3  scale           : gaussiennes géantes (sigma_max > k x médiane) ou aiguilles (anisotropie)
  A3b floaters        : à la fois peu opaques ET grosses (alpha < a ET sigma_max > m x médiane)
  A4  crop            : boîte / sphère manuelle, ou recadrage automatique robuste (quantile)
  A5  sor             : Statistical Outlier Removal (k plus proches voisins, nécessite scipy)
  A6  density         : densité locale sur grille de voxels (27-voisinage), numpy pur

Exemples :
    python3 scripts/clean.py in.ply out.ply --preset medium
    python3 scripts/clean.py in.ply out.ply --min-opacity 0.01 --sor 16 2.0 --box -5 -5 -5 5 5 5
"""
import argparse
import json
import time

import numpy as np

from gsply import load, write_ply, write_splat, human_size

PRESETS = {
    # léger : uniquement ce qui est certainement invisible
    "light": dict(min_opacity=1 / 255),
    # moyen : + géantes, voxels isolés, points très lointains
    "medium": dict(min_opacity=1 / 255, max_scale_mult=30.0, floaters=(0.2, 5.0), auto_crop=(0.99, 2.0),
                   density=(None, 3)),
    # agressif : opacités faibles, SOR, recadrage serré (vérifier visuellement !)
    "aggressive": dict(min_opacity=0.02, max_scale_mult=15.0, floaters=(0.3, 3.0), auto_crop=(0.98, 1.5),
                       sor=(16, 2.0), density=(None, 5)),
}


# ------------------------------------------------------------------ filtres
def mask_finite(g):
    return (np.isfinite(g.xyz).all(1) & np.isfinite(g.scale).all(1) & np.isfinite(g.opacity)
            & np.isfinite(g.rot).all(1) & np.isfinite(g.f_dc).all(1)
            & np.isfinite(g.f_rest.reshape(len(g), -1)).all(1)
            & (np.linalg.norm(g.rot, axis=1) > 1e-8))


def mask_opacity(g, min_alpha):
    return g.alpha >= min_alpha


def mask_scale(g, max_scale_mult=None, max_scale_abs=None, max_aniso=None):
    s = g.sigma
    smax = s.max(1)
    keep = np.ones(len(g), bool)
    if max_scale_mult:
        keep &= smax <= max_scale_mult * np.median(smax)
    if max_scale_abs:
        keep &= smax <= max_scale_abs
    if max_aniso:
        keep &= smax / np.maximum(s.min(1), 1e-12) <= max_aniso
    return keep


def mask_floaters(g, max_alpha=0.2, scale_mult=5.0):
    """Floaters typiques : à la fois peu opaques ET plus grosses que la normale. Aucun des deux
    critères seul ne suffit (les petites gaussiennes transparentes et les grandes opaques sont légitimes)."""
    smax = g.sigma.max(1)
    return ~((g.alpha < max_alpha) & (smax > scale_mult * np.median(smax)))


def mask_box(g, bmin, bmax):
    return ((g.xyz >= np.asarray(bmin)) & (g.xyz <= np.asarray(bmax))).all(1)


def mask_sphere(g, center, radius):
    return np.linalg.norm(g.xyz - np.asarray(center), axis=1) <= radius


def mask_auto_crop(g, q=0.99, factor=2.0):
    """Centre robuste = médiane ; rayon = factor x quantile_q des distances.
    Retire le « halo » de points lointains (ciel, fond mal reconstruit) sans toucher au coeur."""
    c = np.median(g.xyz, 0)
    d = np.linalg.norm(g.xyz - c, axis=1)
    return d <= factor * np.quantile(d, q)


def knn_mean_distance(xyz, k):
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        raise SystemExit("Le filtre SOR nécessite scipy (pip install scipy) ; utilisez --density sinon.")
    tree = cKDTree(xyz)
    d, _ = tree.query(xyz, k=k + 1, workers=-1)  # le 1er voisin est le point lui-même
    return d[:, 1:].mean(1)


def mask_sor(g, k=16, n_sigma=2.0):
    """Statistical Outlier Removal (PCL) : d_i = distance moyenne aux k voisins ;
    on retire les points tels que d_i > mu + n_sigma * std."""
    d = knn_mean_distance(g.xyz.astype(np.float64), k)
    return d <= d.mean() + n_sigma * d.std()


def auto_voxel_size(xyz, factor=2.0):
    lo, hi = np.quantile(xyz, 0.05, 0), np.quantile(xyz, 0.95, 0)
    ext = np.maximum(hi - lo, 1e-6)
    return float(factor * (np.prod(ext) / len(xyz)) ** (1 / 3))


def voxel_neighbor_counts(xyz, voxel):
    """Nombre de points dans le 27-voisinage (3x3x3 voxels) de chaque point, en O(N log N).
    Clés de voxel linéarisées + np.unique + recherche dichotomique des 27 voisins."""
    ijk = np.floor((xyz - xyz.min(0)) / voxel).astype(np.int64) + 1   # +1 : marge pour les voisins
    dims = ijk.max(0) + 2
    if np.prod(dims.astype(np.float64)) > 9e18:
        raise ValueError("Grille trop grande : augmentez la taille de voxel ou recadrez d'abord")
    sy, sz = dims[1] * dims[2], dims[2]
    key = ijk[:, 0] * sy + ijk[:, 1] * sz + ijk[:, 2]
    uniq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    neigh = np.zeros(len(uniq), np.int64)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for dk in (-1, 0, 1):
                nk = uniq + di * sy + dj * sz + dk
                idx = np.searchsorted(uniq, nk)
                idx[idx == len(uniq)] = 0
                found = uniq[idx] == nk
                neigh += np.where(found, cnt[idx], 0)
    return neigh[inv] - 1  # sans le point lui-même


def mask_density(g, voxel=None, min_neighbors=3, voxel_factor=2.0):
    voxel = voxel or auto_voxel_size(g.xyz, voxel_factor)
    return voxel_neighbor_counts(g.xyz.astype(np.float64), voxel) >= min_neighbors, voxel


# ---------------------------------------------------------------- pipeline
def clean(g, min_opacity=None, max_scale_mult=None, max_scale_abs=None, max_aniso=None,
          floaters=None, box=None, sphere=None, auto_crop=None, sor=None, density=None, verbose=True):
    """Applique les filtres en cascade. Retourne (nuage nettoyé, journal)."""
    log, n0 = [], len(g)

    def step(name, keep, info=None):
        nonlocal g
        removed = int((~keep).sum())
        log.append({"filter": name, "removed": removed, "remaining": int(keep.sum()), **(info or {})})
        if verbose:
            print(f"  {name:<10} -{removed:>9}  ({100 * removed / max(n0, 1):5.2f} % du total)  "
                  f"reste {int(keep.sum()):,}".replace(",", " "))
        g = g.subset(keep)

    step("finite", mask_finite(g))
    if min_opacity:
        step("opacity", mask_opacity(g, min_opacity), {"min_alpha": min_opacity})
    if max_scale_mult or max_scale_abs or max_aniso:
        step("scale", mask_scale(g, max_scale_mult, max_scale_abs, max_aniso),
             {"mult": max_scale_mult, "abs": max_scale_abs, "aniso": max_aniso})
    if floaters:
        step("floaters", mask_floaters(g, *floaters), {"max_alpha": floaters[0], "scale_mult": floaters[1]})
    if box is not None:
        step("box", mask_box(g, box[:3], box[3:]))
    if sphere is not None:
        step("sphere", mask_sphere(g, sphere[:3], sphere[3]))
    if auto_crop:
        step("autocrop", mask_auto_crop(g, *auto_crop), {"q": auto_crop[0], "factor": auto_crop[1]})
    if sor:
        step("sor", mask_sor(g, int(sor[0]), float(sor[1])), {"k": int(sor[0]), "n_sigma": float(sor[1])})
    if density:
        keep, vox = mask_density(g, density[0], int(density[1]))
        step("density", keep, {"voxel": vox, "min_neighbors": int(density[1])})
    return g, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output", help=".ply ou .splat")
    ap.add_argument("--preset", choices=PRESETS, help="jeu de paramètres prédéfini (surchargé par les options)")
    ap.add_argument("--min-opacity", type=float)
    ap.add_argument("--max-scale-mult", type=float, help="retire si sigma_max > X * médiane")
    ap.add_argument("--max-scale-abs", type=float, help="retire si sigma_max > X (unités de la scène)")
    ap.add_argument("--max-aniso", type=float, help="retire si sigma_max/sigma_min > X")
    ap.add_argument("--floaters", type=float, nargs=2, metavar=("MAX_ALPHA", "SCALE_MULT"),
                    help="retire si alpha < MAX_ALPHA ET sigma_max > SCALE_MULT * médiane")
    ap.add_argument("--box", type=float, nargs=6, metavar=("XMIN", "YMIN", "ZMIN", "XMAX", "YMAX", "ZMAX"))
    ap.add_argument("--sphere", type=float, nargs=4, metavar=("CX", "CY", "CZ", "R"))
    ap.add_argument("--auto-crop", type=float, nargs=2, metavar=("QUANTILE", "FACTOR"))
    ap.add_argument("--sor", type=float, nargs=2, metavar=("K", "NSIGMA"))
    ap.add_argument("--density", type=float, nargs=2, metavar=("VOXEL", "MIN_NEIGHBORS"),
                    help="VOXEL=0 pour une taille automatique")
    ap.add_argument("--report", help="journal JSON")
    args = ap.parse_args()

    params = dict(PRESETS.get(args.preset, {}))
    for k in ("min_opacity", "max_scale_mult", "max_scale_abs", "max_aniso", "floaters", "box", "sphere",
              "auto_crop", "sor"):
        if getattr(args, k) is not None:
            params[k] = getattr(args, k)
    if args.density is not None:
        params["density"] = (args.density[0] or None, args.density[1])

    t = time.time()
    g = load(args.input)
    n0 = len(g)
    print(f"Entrée : {n0:,} gaussiennes".replace(",", " "))
    g, log = clean(g, **params)
    if args.output.endswith(".splat"):
        write_splat(args.output, g)
    else:
        write_ply(args.output, g)
    print(f"Sortie : {len(g):,} gaussiennes ({100 * len(g) / n0:.1f} %), "
          f"{human_size(__import__('os').path.getsize(args.output))}, {time.time() - t:.1f} s".replace(",", " "))
    if args.report:
        with open(args.report, "w") as f:
            json.dump({"input": args.input, "params": params, "n_in": n0, "n_out": len(g), "steps": log},
                      f, indent=2, default=str)


if __name__ == "__main__":
    main()
