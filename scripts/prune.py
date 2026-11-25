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


def orbit_cameras(xyz, n=32, w=800, h=800, fov_deg=60.0, margin=1.05, up=(0, -1, 0),
                  elevations=(10.0, 35.0, 60.0), azimuth0=0.0):
    """Caméras virtuelles réparties sur plusieurs anneaux d'orbite autour du centre robuste de la scène
    (utile quand les poses d'acquisition ne sont pas disponibles ; scène « objet » plutôt qu'intérieur).

    Distance choisie pour que la sphère englobante robuste (quantile 95 % des distances) tienne
    entièrement dans le champ : r = R / sin(fov/2). Image carrée pour que le champ vertical soit aussi
    large que l'horizontal. Sans cela, le haut des objets sort du cadre, n'est jamais « vu », obtient un
    score nul et est supprimé en bloc (trous)."""
    c = np.median(xyz, 0)
    R_scene = np.quantile(np.linalg.norm(xyz - c, axis=1), 0.95)
    r = margin * R_scene / np.sin(np.radians(fov_deg) / 2)
    up = np.asarray(up, np.float64)
    a = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 0, 1.0])
    e1 = np.cross(up, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    f = 0.5 * w / np.tan(np.radians(fov_deg) / 2)
    cams = []
    for i in range(n):
        th = 2 * np.pi * i / n + np.radians(azimuth0)
        elev = np.radians(elevations[i % len(elevations)])  # anneaux de hauteurs alternées
        C = c + r * (np.cos(elev) * (np.cos(th) * e1 + np.sin(th) * e2) + np.sin(elev) * up)
        z = c - C; z /= np.linalg.norm(z)                  # axe optique
        x = np.cross(z, up); x /= np.linalg.norm(x)         # droite image (x = y ^ z, y = -up)
        y = np.cross(z, x)                                  # bas image
        R = np.stack([x, y, z])
        cams.append(Cam(R, -R @ C, f, f, w / 2, h / 2, w, h, f"orbit_{i}"))
    return cams


def read_gs_cameras(path):
    """Format écrit par train_3dgs.py (data/<scène>_cameras.json) : monde -> caméra, convention OpenCV,
    dans le repère du .ply exporté."""
    d = json.load(open(path))
    return [Cam(c["R"], c["t"], c["fx"], c["fy"], c["cx"], c["cy"], c["w"], c["h"], c.get("name", ""))
            for c in d["cameras"]]


def load_cameras(spec):
    if spec.endswith(".json") and os.path.exists(spec):
        with open(spec) as f:
            head = f.read(200)
        if "gs-cameras-v1" in head:
            return read_gs_cameras(spec)
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


def _neighbor_depth_spread(zbuf):
    """Pour chaque cellule du z-buffer (gh, gw) : écart maximal de profondeur avec ses 8 voisines.
    Grand sur les bords d'objets et les surfaces vues de biais, petit au milieu d'une surface de face."""
    gh, gw = zbuf.shape
    p = np.pad(zbuf, 1, constant_values=np.inf)
    spread = np.zeros_like(zbuf)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            nb = p[1 + di:1 + di + gh, 1 + dj:1 + dj + gw]
            ok = np.isfinite(nb) & np.isfinite(zbuf)
            with np.errstate(invalid="ignore"):  # inf - inf dans les cellules vides, écarté par `ok`
                spread = np.where(ok, np.maximum(spread, nb - zbuf), spread)
    return spread


def importance_views(g, cams, occlusion=False, occ_cell=8, occ_alpha=0.5, occ_tol=0.002):
    """Somme sur les vues de alpha * aire projetée (pixels), avec test d'occultation optionnel.

    Aire projetée d'une ellipse de demi-axes 3*sigma_a, 3*sigma_b (les deux plus grands) vue de face
    à la profondeur z :  A = pi * (3 sigma_a fx / z) * (3 sigma_b fy / z), bornée par la taille de l'image.
    C'est une borne haute (orientation ignorée) mais elle classe correctement les gaussiennes.
    Occultation : z-buffer basse résolution (cellules occ_cell px) rempli par les centres des
    gaussiennes opaques (alpha > occ_alpha). Une gaussienne est visible si elle n'est pas plus loin que
        z_buffer + max(écart de profondeur avec les cellules voisines, 2 sigma_max) + occ_tol * z
    La marge « cellules voisines » évite de déclarer cachées les gaussiennes des zones vues de biais
    (une cellule de 8 px y couvre une grande plage de profondeur) : sans elle, les bords et les pôles
    d'un objet arrondi sont supprimés par plaques.
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
            spread = _neighbor_depth_spread(zbuf.reshape(gh, gw)).ravel()
            margin = np.maximum(spread[cell], 2 * sa) + occ_tol * z
            vis = inside & (z <= zbuf[cell] + margin + 1e-6)
        score += np.where(vis, a * area, 0.0)
    return score


def coverage_voxels(xyz, target=32, iters=4):
    """Indice de voxel par gaussienne, la taille de voxel étant ajustée pour qu'un voxel occupé
    contienne ~target gaussiennes (médiane). Les gaussiennes vivent sur des surfaces : effectif ∝ v²."""
    lo = xyz.min(0)
    ext = np.maximum(np.quantile(xyz, 0.95, 0) - np.quantile(xyz, 0.05, 0), 1e-6)
    v = 2.0 * float((np.prod(ext) / len(xyz)) ** (1 / 3))
    for _ in range(iters):
        ijk = np.floor((xyz - lo) / v).astype(np.int64)
        _, inv, cnt = np.unique(ijk, axis=0, return_inverse=True, return_counts=True)
        v *= np.sqrt(target / max(np.median(cnt), 1))
    ijk = np.floor((xyz - lo) / v).astype(np.int64)
    _, inv = np.unique(ijk, axis=0, return_inverse=True)
    return inv.ravel(), v


def select(score, keep_ratio=None, min_score=None, xyz=None, min_coverage=0.0):
    """Choisit les gaussiennes gardées.

    min_coverage = f > 0 (nécessite xyz) : sélection « stratifiée » qui empêche de vider une zone.
    L'espace est découpé en voxels ; dans chaque voxel, on garde d'office au moins la fraction f des
    gaussiennes utiles (score > 0) — les meilleures du voxel — puis on complète le budget avec les
    meilleurs scores globaux. Le budget total (keep_ratio) est respecté, mais la perte est répartie :
    aucune zone visible ne peut perdre plus de (1 - f) de ses gaussiennes. Les gaussiennes de score
    nul (jamais vues, cachées) ne sont jamais protégées.
    """
    score = np.nan_to_num(score, nan=-np.inf)  # une gaussienne invalide n'est jamais gardée en priorité
    N = len(score)
    if keep_ratio is None:
        return score >= min_score
    k = max(1, int(round(keep_ratio * N)))
    keep = np.zeros(N, bool)
    if min_coverage > 0 and xyz is not None:
        vox, _ = coverage_voxels(np.asarray(xyz, np.float64))
        useful = score > 0
        order = np.lexsort((-score, vox))               # par voxel, puis score décroissant
        vs = vox[order]
        starts = np.r_[0, np.flatnonzero(np.diff(vs)) + 1]
        rank = np.arange(N) - np.repeat(starts, np.diff(np.r_[starts, N]))
        n_useful = np.bincount(vox, weights=useful, minlength=vox.max() + 1)
        quota = np.ceil(min_coverage * n_useful).astype(np.int64)
        guaranteed = order[(rank < quota[vs]) & useful[order]]
        keep[guaranteed] = True
    rest = k - keep.sum()
    if rest > 0:
        s = np.where(keep, -np.inf, score)
        idx = np.argpartition(-s, rest - 1)[:rest]
        keep[idx] = True
    return keep


def compensate(g, keep, score, max_scale=1.6, max_dist=3.0):
    """Élagage avec compensation : la « masse visuelle » (opacité x aire) de chaque gaussienne visible
    supprimée est reportée sur la gaussienne gardée la plus proche, si elle est dans son voisinage
    (distance <= max_dist x sigma_max de la gardée).

    Pour chaque gardée i recevant une masse M_i en plus de sa masse m_i = alpha_i * sigma_a * sigma_b :
      1. opacité : alpha_i' = min(0,99, alpha_i * (m_i + M_i) / m_i)        (reste net)
      2. si l'opacité plafonne, le reste agrandit les deux plus grands axes, facteur <= max_scale ;
      3. couleur (DC et SH) = moyenne pondérée par les masses.
    Les gaussiennes de score nul (jamais vues : cachées) ne sont jamais compensées.
    Sans compensation, la densité d'opacité baisse et on voit à travers les surfaces (aspect « tacheté »).
    """
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        print("compensation ignorée : scipy absent (pip install scipy)")
        return g.subset(keep)
    kept = np.flatnonzero(keep)
    rem = np.flatnonzero(~keep & (np.nan_to_num(score) > 0))
    out = g.subset(kept)
    if not len(rem) or not len(kept):
        return out
    sig = g.sigma.astype(np.float64)
    ss = np.sort(sig, 1)
    area = ss[:, 2] * ss[:, 1]
    alpha = g.alpha.astype(np.float64)
    d, nn = cKDTree(g.xyz[kept].astype(np.float64)).query(g.xyz[rem].astype(np.float64), k=1, workers=-1)
    ok = d <= max_dist * ss[kept[nn], 2]
    rem, nn = rem[ok], nn[ok]
    m_rem = alpha[rem] * area[rem]
    K = len(kept)
    M = np.bincount(nn, weights=m_rem, minlength=K)
    m0 = alpha[kept] * area[kept]
    tot = m0 + M
    ratio = tot / np.maximum(m0, 1e-30)
    a_new = np.minimum(0.99, alpha[kept] * ratio)
    rest = alpha[kept] * ratio / a_new                       # >= 1 : ce que l'opacité n'a pas absorbé
    f = np.minimum(max_scale, np.sqrt(rest))
    out.opacity = np.log(a_new / (1 - a_new)).astype(np.float32)
    big2 = np.argsort(sig[kept], 1)[:, 1:]                   # indices des deux plus grands axes
    sc = out.scale.astype(np.float64)
    np.add.at(sc, (np.repeat(np.arange(K), 2), big2.ravel()), np.repeat(np.log(f), 2))
    out.scale = sc.astype(np.float32)
    w0 = (m0 / tot)[:, None]
    dc_sum = np.stack([np.bincount(nn, weights=m_rem * g.f_dc[rem, c], minlength=K) for c in range(3)], 1)
    out.f_dc = (w0 * g.f_dc[kept] + dc_sum / tot[:, None]).astype(np.float32)
    if g.f_rest.shape[2]:
        R = g.f_rest.reshape(len(g), -1)
        rs = np.stack([np.bincount(nn, weights=m_rem * R[rem, j], minlength=K) for j in range(R.shape[1])], 1)
        out.f_rest = (w0 * R[kept] + rs / tot[:, None]).astype(np.float32).reshape(K, 3, -1)
    return out


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
    ap.add_argument("--min-coverage", type=float, default=0.25, metavar="F",
                    help="anti-trous : chaque zone garde au moins F de ses gaussiennes utiles (0 = désactivé)")
    ap.add_argument("--compensate", action="store_true",
                    help="reporte l'opacité/la couleur des gaussiennes supprimées sur leurs voisines (anti-transparence)")
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
    keep = select(score, args.keep_ratio, args.min_score, xyz=g.xyz, min_coverage=args.min_coverage)
    if args.save_scores:
        np.save(args.save_scores, score)
    out = compensate(g, keep, score) if args.compensate else g.subset(keep)
    (write_splat if args.output.endswith(".splat") else write_ply)(args.output, out)
    print(f"{len(g):,} -> {len(out):,} gaussiennes ({100 * len(out) / len(g):.1f} %) ; "
          f"part du score total conservée : {100 * score[keep].sum() / max(score.sum(), 1e-12):.1f} % ; "
          f"{human_size(os.path.getsize(args.output))} ; {time.time() - t:.1f} s".replace(",", " "))


if __name__ == "__main__":
    main()
