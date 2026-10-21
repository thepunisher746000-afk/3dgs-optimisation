#!/usr/bin/env python3
"""Élagage (pruning) par score d'importance : on ne garde que les gaussiennes qui contribuent
le plus à l'image (voir docs/03_optimisation.md, §3).

Deux scores :
  * proxy  (défaut, sans caméras)   : I_j = alpha_j * min(V_j / V_90, 1)^beta
  * views  (--cameras ou --orbit)   : I_j = sum_cam  alpha_j * aire_projetée_j(cam) * visible_j(cam)
    inspiré de la « Global Significance » de LightGaussian (Fan et al., 2023), où l'aire projetée
    approche le nombre de pixels touchés et `visible` est un test d'occultation grossier (z-buffer).

Sélection : --keep-ratio 0.4 (garde les 40 % les plus importants) ou --min-score.

Exemples :
    python3 scripts/prune.py in.ply out.ply --keep-ratio 0.5
    python3 scripts/prune.py in.ply out.ply --keep-ratio 0.3 --cameras chemin/vers/cameras.json --occlusion
    python3 scripts/prune.py in.ply out.ply --keep-ratio 0.3 --cameras colmap/sparse/0   (cameras.txt, images.txt)
    python3 scripts/prune.py in.ply out.ply --keep-ratio 0.3 --orbit 32
"""
import argparse
import json
import os
import time

import numpy as np

from clean import mask_finite
from gsply import load, write_ply, write_splat, human_size


# ------------------------------------------------------------------ caméras
class Cam:
    """Caméra sténopé : x_cam = R @ x_monde + t (convention OpenCV/COLMAP : z vers l'avant)."""

    def __init__(self, R, t, fx, fy, cx, cy, w, h, name=""):
        self.R, self.t = np.asarray(R, np.float64), np.asarray(t, np.float64)
        self.fx, self.fy, self.cx, self.cy, self.w, self.h, self.name = fx, fy, cx, cy, int(w), int(h), name


def qvec2rotmat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
        [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
        [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y]])


def read_colmap_text(folder):
    """Lit cameras.txt + images.txt (export texte de COLMAP : File > Export model as text)."""
    intr = {}
    for line in open(os.path.join(folder, "cameras.txt")):
        if line.startswith("#") or not line.strip():
            continue
        p = line.split()
        cid, model, w, h, prm = int(p[0]), p[1], int(p[2]), int(p[3]), list(map(float, p[4:]))
        if model in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL", "SIMPLE_RADIAL_FISHEYE"):
            fx = fy = prm[0]; cx, cy = prm[1], prm[2]
        else:  # PINHOLE, OPENCV, FULL_OPENCV, ... -> fx fy cx cy en tête
            fx, fy, cx, cy = prm[:4]
        intr[cid] = (fx, fy, cx, cy, w, h)
    cams, lines = [], [l for l in open(os.path.join(folder, "images.txt")) if not l.startswith("#")]
    for i in range(0, len(lines), 2):  # une ligne pose, une ligne de points 2D
        p = lines[i].split()
        if len(p) < 10:
            continue
        q, t, cid = list(map(float, p[1:5])), list(map(float, p[5:8])), int(p[8])
        cams.append(Cam(qvec2rotmat(q), t, *intr[cid], name=p[9]))
    return cams


def read_inria_cameras_json(path):
    """cameras.json écrit par le code 3DGS original / gsplat : rotation = R caméra->monde, position = centre."""
    cams = []
    for c in json.load(open(path)):
        Rc2w, C = np.array(c["rotation"]), np.array(c["position"])
        R = Rc2w.T
        cams.append(Cam(R, -R @ C, c["fx"], c["fy"], c["width"] / 2, c["height"] / 2,
                        c["width"], c["height"], c.get("img_name", "")))
    return cams


def orbit_cameras(xyz, n=32, w=960, h=540, fov_deg=60.0, radius_mult=1.2, up=(0, -1, 0)):
    """Caméras virtuelles réparties sur une orbite autour du centre robuste de la scène
    (utile quand les poses d'acquisition ne sont pas disponibles ; scène « objet » plutôt qu'intérieur)."""
    c = np.median(xyz, 0)
    r = radius_mult * np.quantile(np.linalg.norm(xyz - c, axis=1), 0.9)
    up = np.asarray(up, np.float64)
    a = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 0, 1.0])
    e1 = np.cross(up, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    f = 0.5 * w / np.tan(np.radians(fov_deg) / 2)
    cams = []
    for i in range(n):
        th = 2 * np.pi * i / n
        elev = np.radians(15 + 20 * (i % 2))  # deux hauteurs alternées
        C = c + r * (np.cos(elev) * (np.cos(th) * e1 + np.sin(th) * e2) + np.sin(elev) * up)
        z = c - C; z /= np.linalg.norm(z)                  # axe optique
        x = np.cross(z, up); x /= np.linalg.norm(x)         # droite image (x = y ^ z, y = -up)
        y = np.cross(z, x)                                  # bas image
        R = np.stack([x, y, z])
        cams.append(Cam(R, -R @ C, f, f, w / 2, h / 2, w, h, f"orbit_{i}"))
    return cams


def load_cameras(spec):
    if os.path.isdir(spec):
        if os.path.exists(os.path.join(spec, "images.txt")):
            return read_colmap_text(spec)
        if os.path.exists(os.path.join(spec, "cameras.json")):
            return read_inria_cameras_json(os.path.join(spec, "cameras.json"))
    if spec.endswith(".json"):
        return read_inria_cameras_json(spec)
    raise SystemExit(f"Format de caméras non reconnu : {spec}")


# ------------------------------------------------------------------- scores
def importance_proxy(g, beta=0.1):
    """Score sans caméra : opacité x volume normalisé^beta (beta petit = le volume ne départage
    que les gaussiennes d'opacité voisine)."""
    V = np.prod(g.sigma.astype(np.float64), 1)
    Vn = np.minimum(V / np.quantile(V, 0.9), 1.0)
    return g.alpha * Vn ** beta


def importance_views(g, cams, occlusion=False, occ_cell=8, occ_alpha=0.5, occ_tol=0.05):
    """Somme sur les vues de alpha * aire projetée (pixels), avec test d'occultation optionnel.

    Aire projetée d'une ellipse de demi-axes 3*sigma_a, 3*sigma_b (les deux plus grands) vue de face
    à la profondeur z :  A = pi * (3 sigma_a fx / z) * (3 sigma_b fy / z), bornée par la taille de l'image.
    C'est une borne haute (orientation ignorée) mais elle classe correctement les gaussiennes.
    Occultation : z-buffer basse résolution (cellules occ_cell px) rempli par les centres des
    gaussiennes opaques (alpha > occ_alpha) ; une gaussienne derrière ce z-buffer n'est pas comptée.
    """
    xyz = g.xyz.astype(np.float64)
    a = g.alpha.astype(np.float64)
    s = np.sort(g.sigma.astype(np.float64), 1)
    sa, sb = s[:, 2], s[:, 1]
    score = np.zeros(len(g))
    opaque = a > occ_alpha
    for cam in cams:
        pc = xyz @ cam.R.T + cam.t
        z = pc[:, 2]
        front = z > 1e-3
        zz = np.where(front, z, 1.0)
        u = cam.fx * pc[:, 0] / zz + cam.cx
        v = cam.fy * pc[:, 1] / zz + cam.cy
        ra = 3 * sa * cam.fx / zz
        inside = front & (u > -ra) & (u < cam.w + ra) & (v > -ra) & (v < cam.h + ra)
        area = np.minimum(np.pi * ra * (3 * sb * cam.fy / zz), cam.w * cam.h)
        vis = inside
        if occlusion:
            gw, gh = cam.w // occ_cell + 1, cam.h // occ_cell + 1
            iu = np.clip((u // occ_cell).astype(np.int64), 0, gw - 1)
            iv = np.clip((v // occ_cell).astype(np.int64), 0, gh - 1)
            cell = iv * gw + iu
            zbuf = np.full(gw * gh, np.inf)
            m = inside & opaque & (u >= 0) & (u < cam.w) & (v >= 0) & (v < cam.h)
            np.minimum.at(zbuf, cell[m], z[m])
            vis = inside & (z <= zbuf[cell] * (1 + occ_tol) + 1e-6)
        score += np.where(vis, a * area, 0.0)
    return score


def select(score, keep_ratio=None, min_score=None):
    score = np.nan_to_num(score, nan=-np.inf)  # une gaussienne invalide n'est jamais gardée en priorité
    if keep_ratio is not None:
        k = max(1, int(round(keep_ratio * len(score))))
        idx = np.argpartition(-score, k - 1)[:k]
        keep = np.zeros(len(score), bool)
        keep[idx] = True
        return keep
    return score >= min_score


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--keep-ratio", type=float, help="fraction de gaussiennes à garder (0-1)")
    grp.add_argument("--min-score", type=float)
    ap.add_argument("--cameras", help="dossier COLMAP texte, ou cameras.json (3DGS/gsplat)")
    ap.add_argument("--orbit", type=int, help="génère N caméras virtuelles en orbite")
    ap.add_argument("--up", type=float, nargs=3, default=(0, -1, 0), help="axe vertical (orbite)")
    ap.add_argument("--occlusion", action="store_true", help="test d'occultation par z-buffer grossier")
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--save-scores", help="sauve les scores (.npy) pour analyse")
    args = ap.parse_args()

    t = time.time()
    g = load(args.input)
    finite = mask_finite(g)
    if not finite.all():
        print(f"{(~finite).sum()} gaussiennes non finies (NaN/Inf) retirées au préalable")
        g = g.subset(finite)
    if args.cameras or args.orbit:
        cams = load_cameras(args.cameras) if args.cameras else orbit_cameras(g.xyz, args.orbit, up=args.up)
        print(f"Score « views » sur {len(cams)} caméras (occultation={args.occlusion})")
        score = importance_views(g, cams, occlusion=args.occlusion)
    else:
        print("Score « proxy » (opacité x volume^beta)")
        score = importance_proxy(g, args.beta)
    keep = select(score, args.keep_ratio, args.min_score)
    if args.save_scores:
        np.save(args.save_scores, score)
    out = g.subset(keep)
    (write_splat if args.output.endswith(".splat") else write_ply)(args.output, out)
    print(f"{len(g):,} -> {len(out):,} gaussiennes ({100 * len(out) / len(g):.1f} %) ; "
          f"part du score total conservée : {100 * score[keep].sum() / max(score.sum(), 1e-12):.1f} % ; "
          f"{human_size(os.path.getsize(args.output))} ; {time.time() - t:.1f} s".replace(",", " "))


if __name__ == "__main__":
    main()
