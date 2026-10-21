#!/usr/bin/env python3
"""Génère une scène 3DGS synthétique (degré SH 3) avec des défauts typiques connus à l'avance,
pour valider la chaîne d'optimisation avant d'avoir une vraie capture :

  * sol damier (gaussiennes plates), sphère brillante (SH non nuls), cube texturé  -> « vrai » contenu
  * gaussiennes cachées (intérieur de la sphère et du cube, sous le sol) : redondance invisible, comme
    celle créée par la densification ; un bon élagage doit les retirer en premier
  * floaters : grosses gaussiennes peu opaques flottant dans le vide
  * gaussiennes quasi transparentes (alpha < 1/255) mêlées au contenu
  * halo de points très lointains (ciel / fond mal reconstruit)
  * quelques NaN

Convention « COLMAP » : axe y vers le bas (régler cameraUp = 0,-1,0 dans le visualiseur).

    python3 scripts/make_synthetic.py data/synthetic.ply --n 300000
"""
import argparse

import numpy as np

from gsply import GaussianCloud, write_ply, logit, SH_C0


def random_quats(rng, n):
    q = rng.normal(size=(n, 4))
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def quat_aligning_z_to(normals):
    """Quaternion (w,x,y,z) qui tourne l'axe z local sur la normale donnée."""
    z = np.array([0.0, 0, 1])
    v = np.cross(np.broadcast_to(z, normals.shape), normals)
    w = 1.0 + normals @ z
    q = np.concatenate([w[:, None], v], 1)
    bad = w < 1e-6
    q[bad] = [0, 1, 0, 0]
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def make(n=300_000, seed=0):
    rng = np.random.default_rng(seed)
    parts = []

    def block(xyz, rgb, alpha, sigma, rot, sh_amp):
        m = len(xyz)
        f_rest = rng.normal(scale=sh_amp, size=(m, 3, 15)) * np.exp(-0.3 * np.arange(15))[None, None, :]
        parts.append(GaussianCloud(
            xyz.astype(np.float32), ((rgb - 0.5) / SH_C0).astype(np.float32), f_rest.astype(np.float32),
            logit(alpha).astype(np.float32), np.log(sigma).astype(np.float32), rot.astype(np.float32)))

    n_floor, n_sphere, n_cube, n_hidden = int(0.35 * n), int(0.2 * n), int(0.15 * n), int(0.2 * n)
    # sol damier (plan y = 0), gaussiennes plates
    p = rng.uniform(-4, 4, size=(n_floor, 2))
    xyz = np.stack([p[:, 0], np.zeros(n_floor), p[:, 1]], 1)
    checker = ((np.floor(p[:, 0]) + np.floor(p[:, 1])) % 2)[:, None]
    rgb = 0.15 + 0.7 * checker * np.array([0.9, 0.85, 0.7]) + rng.normal(0, 0.02, (n_floor, 3))
    sig = np.stack([rng.uniform(0.01, 0.03, n_floor)] * 2 + [np.full(n_floor, 0.001)], 1)
    block(xyz, np.clip(rgb, 0, 1), rng.uniform(0.6, 1.0, n_floor), sig,
          quat_aligning_z_to(np.tile([0, -1.0, 0], (n_floor, 1))), 0.02)
    # sphère brillante (SH forts)
    d = rng.normal(size=(n_sphere, 3)); d /= np.linalg.norm(d, axis=1, keepdims=True)
    xyz = np.array([0, -1.0, 0]) + 0.9 * d
    rgb = 0.5 + 0.4 * d[:, [0, 2, 1]] * np.array([1, 0.6, -0.8])
    sig = np.stack([rng.uniform(0.01, 0.025, n_sphere)] * 2 + [np.full(n_sphere, 0.002)], 1)
    block(xyz, np.clip(rgb, 0, 1), rng.uniform(0.7, 1.0, n_sphere), sig, quat_aligning_z_to(d), 0.25)
    # cube texturé
    face = rng.integers(0, 6, n_cube)
    uv = rng.uniform(-0.5, 0.5, size=(n_cube, 2))
    axis, sign = face // 2, np.where(face % 2, 1.0, -1.0)
    xyz = np.zeros((n_cube, 3)); nrm = np.zeros((n_cube, 3))
    for a in range(3):
        m = axis == a
        others = [i for i in range(3) if i != a]
        xyz[m, a] = 0.5 * sign[m]; xyz[m, others[0]] = uv[m, 0]; xyz[m, others[1]] = uv[m, 1]
        nrm[m, a] = sign[m]
    xyz += np.array([2.2, -0.5, 1.0])
    stripes = (np.sin(uv[:, 0] * 25) > 0)[:, None]
    rgb = np.where(stripes, [0.8, 0.2, 0.15], [0.95, 0.9, 0.85])
    sig = np.stack([rng.uniform(0.008, 0.02, n_cube)] * 2 + [np.full(n_cube, 0.001)], 1)
    block(xyz, rgb, rng.uniform(0.8, 1.0, n_cube), sig, quat_aligning_z_to(nrm), 0.03)

    # gaussiennes cachées : intérieur de la sphère, du cube, et sous le sol (y > 0, axe y vers le bas)
    h1, h2 = n_hidden // 3, n_hidden // 3
    h3 = n_hidden - h1 - h2
    d = rng.normal(size=(h1, 3)); d /= np.linalg.norm(d, axis=1, keepdims=True)
    hid = [np.array([0, -1.0, 0]) + d * 0.75 * rng.uniform(0, 1, (h1, 1)) ** (1 / 3),
           np.array([2.2, -0.5, 1.0]) + rng.uniform(-0.35, 0.35, (h2, 3)),
           np.stack([rng.uniform(-4, 4, h3), rng.uniform(0.15, 0.4, h3), rng.uniform(-4, 4, h3)], 1)]
    xyz = np.concatenate(hid)
    block(xyz, rng.uniform(0.2, 0.8, (n_hidden, 3)), rng.uniform(0.5, 1.0, n_hidden),
          rng.uniform(0.01, 0.04, (n_hidden, 3)), random_quats(rng, n_hidden), 0.05)

    # ---- défauts
    n_def = n - n_floor - n_sphere - n_cube - n_hidden
    n_float, n_transp, n_halo = int(0.35 * n_def), int(0.45 * n_def), n_def - int(0.35 * n_def) - int(0.45 * n_def)
    block(rng.uniform([-4, -3, -4], [4, -0.2, 4], size=(n_float, 3)), rng.uniform(0, 1, (n_float, 3)),
          rng.uniform(0.01, 0.15, n_float), rng.uniform(0.05, 0.4, (n_float, 3)), random_quats(rng, n_float), 0.1)
    idx = rng.integers(0, n_floor + n_sphere + n_cube, n_transp)
    allc = np.concatenate([q.xyz for q in parts[:3]])
    block(allc[idx] + rng.normal(0, 0.02, (n_transp, 3)), rng.uniform(0, 1, (n_transp, 3)),
          rng.uniform(1e-4, 3e-3, n_transp), rng.uniform(0.005, 0.05, (n_transp, 3)), random_quats(rng, n_transp), 0.05)
    d = rng.normal(size=(n_halo, 3)); d /= np.linalg.norm(d, axis=1, keepdims=True)
    block(d * rng.uniform(30, 80, (n_halo, 1)), np.tile([0.55, 0.7, 0.9], (n_halo, 1)),
          rng.uniform(0.2, 0.9, n_halo), rng.uniform(0.5, 3.0, (n_halo, 3)), random_quats(rng, n_halo), 0.02)

    g = GaussianCloud(*[np.concatenate([getattr(q, k) for q in parts]) for k in
                        ("xyz", "f_dc", "f_rest", "opacity", "scale", "rot")])
    g.xyz[rng.integers(0, len(g), 5)] = np.nan
    perm = rng.permutation(len(g))  # mélange (comme une sortie d'entraînement)
    return g.subset(perm)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output")
    ap.add_argument("--n", type=int, default=300_000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    g = make(args.n, args.seed)
    write_ply(args.output, g, normals=True)
    print(f"{len(g):,} gaussiennes -> {args.output}".replace(",", " "))


if __name__ == "__main__":
    main()
