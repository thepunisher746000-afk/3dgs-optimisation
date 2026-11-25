#!/usr/bin/env python3
"""Rendu de référence d'un modèle 3DGS sur CPU (numpy), pour mesurer la qualité sans navigateur.

Reproduit le rasteriseur de 3DGS (Kerbl et al. 2023) :
  * projection EWA : Sigma2D = J W Sigma W^T J^T + 0,3 I (filtre passe-bas d'un pixel) ;
  * couleur par harmoniques sphériques (degré 0 à 3) évaluées dans la direction caméra -> gaussienne ;
  * composition alpha avant -> arrière EXACTE : chaque gaussienne produit des « fragments » (pixel,
    profondeur, alpha, couleur) ; on trie les fragments par (pixel, profondeur) puis on calcule la
    transmittance T_i = prod_{k<i} (1 - alpha_k) par somme cumulée segmentée de log(1 - alpha).
Plus lent qu'un GPU (quelques secondes par image en 480x360) mais déterministe et indépendant du
navigateur : c'est l'outil de mesure du benchmark.

    python3 scripts/render.py scene.ply out.png --orbit 8 --view 3 --size 480 360
"""
import argparse
import zlib
import struct

import numpy as np

from gsply import SH_C0

SH_C1 = 0.4886025119029199
SH_C2 = (1.0925484305920792, -1.0925484305920792, 0.31539156525252005, -1.0925484305920792, 0.5462742152960396)
SH_C3 = (-0.5900435899266435, 2.890611442640554, -0.4570457994644658, 0.3731763325901154,
         -0.4570457994644658, 1.445305721320277, -0.5900435899266435)
MAX_RADIUS = 96  # rayon écran max d'un splat (px) : borne la mémoire, comme les visualiseurs web


def quat_to_rotmat(q):
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    w, x, y, z = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1)], 1)


def eval_sh(f_dc, f_rest, dirs, degree=3):
    """Couleur RGB (N,3) dans [0, +inf) pour des directions unitaires (N,3)."""
    res = SH_C0 * f_dc
    K = f_rest.shape[2]
    if degree < 1 or K < 3:
        return np.maximum(res + 0.5, 0)
    x, y, z = dirs[:, 0:1], dirs[:, 1:2], dirs[:, 2:3]
    sh = lambda k: f_rest[:, :, k]
    res = res - SH_C1 * y * sh(0) + SH_C1 * z * sh(1) - SH_C1 * x * sh(2)
    if degree >= 2 and K >= 8:
        xx, yy, zz, xy, yz, xz = x * x, y * y, z * z, x * y, y * z, x * z
        res = (res + SH_C2[0] * xy * sh(3) + SH_C2[1] * yz * sh(4) + SH_C2[2] * (2 * zz - xx - yy) * sh(5)
               + SH_C2[3] * xz * sh(6) + SH_C2[4] * (xx - yy) * sh(7))
        if degree >= 3 and K >= 15:
            res = (res + SH_C3[0] * y * (3 * xx - yy) * sh(8) + SH_C3[1] * xy * z * sh(9)
                   + SH_C3[2] * y * (4 * zz - xx - yy) * sh(10) + SH_C3[3] * z * (2 * zz - 3 * xx - 3 * yy) * sh(11)
                   + SH_C3[4] * x * (4 * zz - xx - yy) * sh(12) + SH_C3[5] * z * (xx - yy) * sh(13)
                   + SH_C3[6] * x * (xx - 3 * yy) * sh(14))
    return np.maximum(res + 0.5, 0)


def project(g, cam, sh_degree=3):
    """Projection de toutes les gaussiennes : centres écran, conique 2D, rayon, profondeur, couleur."""
    xyz = g.xyz.astype(np.float64)
    pc = xyz @ cam.R.T + cam.t
    z = pc[:, 2]
    ok = z > 0.05
    idx = np.flatnonzero(ok)
    pc, z = pc[ok], z[ok]
    tanx, tany = 0.5 * cam.w / cam.fx, 0.5 * cam.h / cam.fy
    tx = np.clip(pc[:, 0] / z, -1.3 * tanx, 1.3 * tanx) * z
    ty = np.clip(pc[:, 1] / z, -1.3 * tany, 1.3 * tany) * z
    J = np.zeros((len(z), 2, 3))
    J[:, 0, 0] = cam.fx / z
    J[:, 0, 2] = -cam.fx * tx / (z * z)
    J[:, 1, 1] = cam.fy / z
    J[:, 1, 2] = -cam.fy * ty / (z * z)
    Rg = quat_to_rotmat(g.rot[idx].astype(np.float64))
    S = np.exp(g.scale[idx].astype(np.float64))
    M = Rg * S[:, None, :]                                    # R S
    cov3 = M @ M.transpose(0, 2, 1)                           # R S S^T R^T
    T = J @ cam.R[None]                                       # J W
    cov2 = T @ cov3 @ T.transpose(0, 2, 1)
    a, b, c = cov2[:, 0, 0] + 0.3, cov2[:, 0, 1], cov2[:, 1, 1] + 0.3
    det = a * c - b * b
    good = det > 0
    mid = 0.5 * (a + c)
    lam = mid + np.sqrt(np.maximum(0.1, mid * mid - det))
    radius = np.minimum(np.ceil(3 * np.sqrt(lam)), MAX_RADIUS)
    u = cam.fx * pc[:, 0] / z + cam.cx - 0.5
    v = cam.fy * pc[:, 1] / z + cam.cy - 0.5
    on = good & (u + radius >= 0) & (u - radius < cam.w) & (v + radius >= 0) & (v - radius < cam.h)
    sel = idx[on]
    inv = 1 / det[on]
    conic = np.stack([c[on] * inv, -b[on] * inv, a[on] * inv], 1)
    campos = -cam.R.T @ cam.t
    dirs = xyz[sel] - campos
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    rgb = eval_sh(g.f_dc[sel].astype(np.float64), g.f_rest[sel].astype(np.float64), dirs, sh_degree)
    alpha = 1 / (1 + np.exp(-g.opacity[sel].astype(np.float64)))
    return u[on], v[on], conic, radius[on].astype(np.int64), z[on], rgb, alpha


def render(g, cam, sh_degree=3, bg=(0.0, 0.0, 0.0), max_fragments=12_000_000, return_stats=False):
    """Image RGB float (h, w, 3) dans [0, 1].
    return_stats=True -> (image, {"overdraw": fragments composés par pixel}) : le surdessin est
    l'indicateur du coût d'affichage sur GPU (chaque fragment = un mélange alpha par pixel)."""
    W, H = cam.w, cam.h
    u, v, conic, rad, z, rgb, alpha = project(g, cam, sh_degree)
    pix, dep, al, col = [], [], [], []
    for r in np.unique(rad):                                   # gaussiennes regroupées par rayon
        m = np.flatnonzero(rad == r)
        off = np.arange(-r, r + 1)
        ox, oy = np.meshgrid(off, off)
        ox, oy = ox.ravel(), oy.ravel()
        step = max(1, int(max_fragments // max(len(ox), 1) // 4))
        for s in range(0, len(m), step):
            mm = m[s:s + step]
            cx, cy = np.round(u[mm]).astype(np.int64), np.round(v[mm]).astype(np.int64)
            px = cx[:, None] + ox[None]
            py = cy[:, None] + oy[None]
            dx = px - u[mm, None]
            dy = py - v[mm, None]
            pw = 0.5 * (conic[mm, 0, None] * dx * dx + conic[mm, 2, None] * dy * dy) + conic[mm, 1, None] * dx * dy
            a = np.minimum(0.99, alpha[mm, None] * np.exp(-pw))
            keep = (pw >= 0) & (a >= 1 / 255) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
            gi = np.broadcast_to(mm[:, None], keep.shape)[keep]
            pix.append((py * W + px)[keep])
            dep.append(z[gi])
            al.append(a[keep])
            col.append(gi)
    img = np.empty((H * W, 3))
    img[:] = bg
    if not pix:
        return (img.reshape(H, W, 3), {"overdraw": 0.0}) if return_stats else img.reshape(H, W, 3)
    pix, dep, al, gi = (np.concatenate(x) for x in (pix, dep, al, col))
    order = np.lexsort((dep, pix))                              # par pixel, puis du plus proche au plus loin
    pix, al, gi = pix[order], al[order], gi[order]
    la = np.log1p(-al)
    csum = np.cumsum(la)
    starts = np.r_[0, np.flatnonzero(np.diff(pix)) + 1]
    seg_start = np.repeat(starts, np.diff(np.r_[starts, len(pix)]))
    base = np.where(seg_start > 0, csum[seg_start - 1], 0.0)
    T_before = np.exp(csum - la - base)                         # transmittance avant ce fragment
    w = T_before * al
    w[T_before < 1e-4] = 0                                      # arrêt anticipé, comme 3DGS
    out = np.zeros((H * W, 3))
    for ch in range(3):
        out[:, ch] = np.bincount(pix, weights=w * rgb[gi, ch], minlength=H * W)
    T_final = np.ones(H * W)
    last = np.r_[starts[1:] - 1, len(pix) - 1]
    T_final[pix[last]] = np.exp(csum[last] - base[last])
    out += T_final[:, None] * np.asarray(bg)[None]
    img = np.clip(out, 0, 1).reshape(H, W, 3)
    if return_stats:
        return img, {"overdraw": float((w > 0).sum()) / (H * W)}
    return img


def write_png(path, img):
    """PNG RGB 8 bits sans dépendance (zlib)."""
    a = np.clip(np.round(np.asarray(img) * 255), 0, 255).astype(np.uint8)
    h, w = a.shape[:2]
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main():
    from gsply import load
    from prune import orbit_cameras
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output", help=".png")
    ap.add_argument("--orbit", type=int, default=8)
    ap.add_argument("--view", type=int, default=0)
    ap.add_argument("--size", type=int, nargs=2, default=(480, 360))
    ap.add_argument("--sh", type=int, default=3)
    args = ap.parse_args()
    g = load(args.input)
    cam = orbit_cameras(g.xyz, args.orbit, w=args.size[0], h=args.size[1])[args.view]
    write_png(args.output, render(g, cam, args.sh))


if __name__ == "__main__":
    main()
