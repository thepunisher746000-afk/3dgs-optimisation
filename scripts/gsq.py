#!/usr/bin/env python3
"""GSQ : codec expérimental de compression de gaussiennes (quantification + codage entropique).

Objectif pédagogique : rendre explicites et mesurables les briques utilisées par les formats
compressés (PlayCanvas compressed.ply / SOG, Niantic SPZ, LightGaussian, C3DGS...). Spécification
complète dans docs/03_optimisation.md, §5-6.

Chaîne d'encodage :
  1. tri de Morton (courbe en Z) -> gaussiennes proches dans l'espace = proches dans le fichier
  2. découpage en blocs de 256 ; bornes min/max par bloc pour positions et log-échelles
  3. quantification uniforme :
       position     16 bits/axe (ou 11-10-11 bits dans un uint32) relative au bloc
       log-échelle   8 bits/axe relative au bloc
       rotation     « smallest three » : 2 bits d'indice + 3 x 10 bits  (uint32)
       couleur DC    8 bits/canal (plage globale robuste)
       opacité       8 bits (sur alpha = sigmoid(o))
       SH ordre>=1   aucun | 8 bits/coef | quantification vectorielle (k-means, index uint16)
  4. « byte shuffle » (octets de poids fort/faible regroupés) puis LZMA ou zlib.

    python3 scripts/gsq.py encode in.ply out.gsq --sh vq --codebook 4096
    python3 scripts/gsq.py decode out.gsq decoded.ply        # pour visualiser / mesurer la qualité
"""
import argparse
import json
import lzma
import os
import struct
import time
import zlib

import numpy as np

from gsply import GaussianCloud, load, write_ply, sigmoid, logit, human_size, SH_REST_PER_DEGREE

MAGIC = b"GSQ1"
CHUNK = 256


# ================================================================ briques
def _part1by2(x):
    """Intercale 2 bits nuls entre chaque bit (21 bits -> 63 bits)."""
    x = x.astype(np.uint64) & np.uint64(0x1FFFFF)
    x = (x | (x << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
    x = (x | (x << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
    x = (x | (x << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
    x = (x | (x << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
    x = (x | (x << np.uint64(2))) & np.uint64(0x1249249249249249)
    return x


def morton_codes(xyz, bits=21):
    lo, hi = xyz.min(0), xyz.max(0)
    q = np.round((xyz - lo) / np.maximum(hi - lo, 1e-12) * (2 ** bits - 1)).astype(np.uint64)
    return _part1by2(q[:, 0]) | (_part1by2(q[:, 1]) << np.uint64(1)) | (_part1by2(q[:, 2]) << np.uint64(2))


def morton_order(xyz):
    return np.argsort(morton_codes(xyz.astype(np.float64)), kind="stable")


def quantize(x, lo, hi, bits):
    levels = (1 << bits) - 1
    t = (np.clip(x, lo, hi) - lo) / np.maximum(hi - lo, 1e-12)
    return np.round(t * levels).astype(np.uint32)


def dequantize(q, lo, hi, bits):
    return lo + q.astype(np.float64) / ((1 << bits) - 1) * (hi - lo)


def chunk_bounds(x, chunk=CHUNK):
    starts = np.arange(0, len(x), chunk)
    return np.minimum.reduceat(x, starts, axis=0), np.maximum.reduceat(x, starts, axis=0)


def encode_quaternions(q):
    """Smallest-three : on normalise, on rend positive la plus grande composante (q et -q représentent
    la même rotation), on stocke son indice (2 bits) et les 3 autres dans [-1/sqrt2, 1/sqrt2] (10 bits)."""
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    idx = np.abs(q).argmax(1)
    q = q * np.sign(q[np.arange(len(q)), idx])[:, None]
    onehot = np.zeros(q.shape, bool)
    onehot[np.arange(len(q)), idx] = True
    others = q[~onehot].reshape(-1, 3)
    v = quantize(others * np.sqrt(2) * 0.5 + 0.5, 0.0, 1.0, 10)
    return (idx.astype(np.uint32) << 30) | (v[:, 0] << 20) | (v[:, 1] << 10) | v[:, 2]


def decode_quaternions(p):
    p = p.astype(np.uint32)
    idx = (p >> 30).astype(np.int64)
    v = np.stack([(p >> 20) & 1023, (p >> 10) & 1023, p & 1023], 1)
    others = (dequantize(v, 0.0, 1.0, 10) - 0.5) / (np.sqrt(2) * 0.5)
    largest = np.sqrt(np.maximum(0.0, 1.0 - (others ** 2).sum(1)))
    q = np.zeros((len(p), 4))
    onehot = np.zeros(q.shape, bool)
    onehot[np.arange(len(p)), idx] = True
    q[onehot] = largest
    q[~onehot] = others.ravel()
    return q


def kmeans(X, K, iters=10, sample=200_000, seed=0, verbose=True):
    """k-means de Lloyd sur un sous-échantillon, initialisation aléatoire, réaffectation des
    centres vides. Complexité O(iters * sample * K * D)."""
    rng = np.random.default_rng(seed)
    S = X[rng.choice(len(X), sample, replace=False)] if len(X) > sample else X
    K = min(K, len(S))
    C = S[rng.choice(len(S), K, replace=False)].astype(np.float32).copy()
    for it in range(iters):
        lab = assign(S, C)
        order = np.argsort(lab, kind="stable")
        ls = lab[order]
        present, starts = np.unique(ls, return_index=True)
        sums = np.add.reduceat(S[order], starts, axis=0)
        cnt = np.diff(np.append(starts, len(ls)))
        newC = C.copy()
        newC[present] = sums / cnt[:, None]
        empty = np.setdiff1d(np.arange(K), present)
        if len(empty):
            newC[empty] = S[rng.choice(len(S), len(empty), replace=False)]
        shift = float(np.abs(newC - C).max())
        C = newC
        if verbose:
            print(f"    k-means it {it + 1:2d}/{iters}  déplacement max {shift:.2e}  vides {len(empty)}")
        if shift < 1e-5:
            break
    return C


def assign(X, C, batch=32768):
    Cn = (C.astype(np.float32) ** 2).sum(1)
    out = np.empty(len(X), np.int64)
    Ct = C.astype(np.float32).T
    for i in range(0, len(X), batch):
        xb = X[i:i + batch].astype(np.float32)
        out[i:i + batch] = (Cn[None, :] - 2.0 * (xb @ Ct)).argmin(1)
    return out


def shuffle_bytes(a):
    a = np.ascontiguousarray(a).reshape(-1)
    s = a.dtype.itemsize
    return a.view(np.uint8).reshape(-1, s).T.tobytes() if s > 1 else a.tobytes()


def unshuffle_bytes(b, dtype, count):
    dtype = np.dtype(dtype)
    s = dtype.itemsize
    u = np.frombuffer(b, np.uint8)
    if s > 1:
        u = np.ascontiguousarray(u.reshape(s, count).T)
    return u.view(dtype).reshape(-1)


# ================================================================ encodage
def encode(g: GaussianCloud, pos_mode="16", sh="vq", codebook=4096, sh_zero=0.0,
           entropy="lzma", kmeans_iters=10, verbose=True):
    """Retourne (octets du fichier, nuage réordonné (Morton), stats)."""
    t0 = time.time()
    from clean import mask_finite
    g = g.subset(mask_finite(g))
    g = g.subset(morton_order(g.xyz))
    N, Kr = len(g), g.f_rest.shape[2]
    if sh == "none":
        Kr = 0
    hdr = {"version": 1, "n": N, "chunk": CHUNK, "pos_mode": pos_mode, "sh_mode": sh if Kr else "none",
           "sh_degree": {v: k for k, v in SH_REST_PER_DEGREE.items()}[Kr], "entropy": entropy}
    sections = []

    def add(name, arr):
        sections.append((name, np.ascontiguousarray(arr)))

    # --- positions (par bloc)
    xyz = g.xyz.astype(np.float64)
    pmin, pmax = chunk_bounds(xyz)
    ci = np.arange(N) // CHUNK
    lo, hi = pmin[ci], pmax[ci]
    if pos_mode == "16":
        add("pos", quantize(xyz, lo, hi, 16).astype(np.uint16))
    else:  # 11-10-11
        qx, qy, qz = quantize(xyz[:, 0], lo[:, 0], hi[:, 0], 11), quantize(xyz[:, 1], lo[:, 1], hi[:, 1], 10), \
            quantize(xyz[:, 2], lo[:, 2], hi[:, 2], 11)
        add("pos", (qx << 21) | (qy << 11) | qz)
    add("pos_bounds", np.concatenate([pmin, pmax], 1).astype(np.float32))

    # --- log-échelles (par bloc, 8 bits)
    ls = g.scale.astype(np.float64)
    smin, smax = chunk_bounds(ls)
    add("scale", quantize(ls, smin[ci], smax[ci], 8).astype(np.uint8))
    add("scale_bounds", np.concatenate([smin, smax], 1).astype(np.float32))

    # --- rotation
    add("rot", encode_quaternions(g.rot.astype(np.float64)))

    # --- couleur DC + opacité
    dlo, dhi = np.quantile(g.f_dc, 0.0005, 0), np.quantile(g.f_dc, 0.9995, 0)
    hdr["dc_range"] = [dlo.tolist(), dhi.tolist()]
    add("dc", quantize(g.f_dc, dlo, dhi, 8).astype(np.uint8))
    add("alpha", quantize(g.alpha, 0.0, 1.0, 8).astype(np.uint8))

    # --- SH d'ordre >= 1
    if Kr:
        R = g.f_rest.reshape(N, 3 * Kr).astype(np.float32)
        if sh == "8bit":
            r = float(np.quantile(np.abs(R), 0.999))
            hdr["sh_range"] = r
            add("sh", quantize(R, -r, r, 8).astype(np.uint8))
        elif sh == "vq":
            e = np.linalg.norm(R, axis=1) / np.maximum(np.linalg.norm(g.f_dc, axis=1), 1e-6)
            zero = e < sh_zero if sh_zero > 0 else np.zeros(N, bool)
            if verbose:
                print(f"  VQ des SH : {N - zero.sum():,} vecteurs de dim {3 * Kr}, "
                      f"{zero.mean() * 100:.1f} % mis à zéro, dictionnaire {codebook}".replace(",", " "))
            C = kmeans(R[~zero], codebook - 1, iters=kmeans_iters, verbose=verbose)
            C = np.concatenate([np.zeros((1, 3 * Kr), np.float32), C])  # entrée 0 = SH nuls
            idx = np.zeros(N, np.int64)
            idx[~zero] = assign(R[~zero], C[1:]) + 1
            hdr["codebook_size"] = len(C)
            add("sh_codebook", C.astype(np.float16))
            add("sh_index", idx.astype(np.uint16 if len(C) <= 65536 else np.uint32))
        else:
            raise ValueError(sh)

    # --- sérialisation
    payload, desc = [], []
    for name, arr in sections:
        payload.append(shuffle_bytes(arr))
        desc.append({"name": name, "dtype": arr.dtype.str, "shape": list(arr.shape)})
    hdr["sections"] = desc
    raw = b"".join(payload)
    comp = {"lzma": lambda b: lzma.compress(b, preset=6), "zlib": lambda b: zlib.compress(b, 9),
            "none": lambda b: b}[entropy](raw)
    hj = json.dumps(hdr).encode()
    blob = MAGIC + struct.pack("<I", len(hj)) + hj + comp
    stats = {"n": N, "raw_bytes": len(raw), "file_bytes": len(blob),
             "bytes_per_gaussian": len(blob) / max(N, 1), "encode_s": time.time() - t0,
             "sections_raw_bytes": {n: int(a.nbytes) for n, a in sections}}
    return blob, g, stats


def decode(blob) -> GaussianCloud:
    assert blob[:4] == MAGIC, "pas un fichier GSQ"
    hl = struct.unpack("<I", blob[4:8])[0]
    hdr = json.loads(blob[8:8 + hl])
    data = {"lzma": lzma.decompress, "zlib": zlib.decompress, "none": lambda b: b}[hdr["entropy"]](blob[8 + hl:])
    arrs, off = {}, 0
    for d in hdr["sections"]:
        dt, shape = np.dtype(d["dtype"]), tuple(d["shape"])
        count = int(np.prod(shape))
        nb = count * dt.itemsize
        arrs[d["name"]] = unshuffle_bytes(data[off:off + nb], dt, count).reshape(shape)
        off += nb

    N, ci = hdr["n"], np.arange(hdr["n"]) // hdr["chunk"]
    pb = arrs["pos_bounds"].astype(np.float64)
    lo, hi = pb[ci, :3], pb[ci, 3:]
    p = arrs["pos"]
    if hdr["pos_mode"] == "16":
        xyz = dequantize(p, lo, hi, 16)
    else:
        p = p.astype(np.uint32)
        xyz = np.stack([dequantize(p >> 21, lo[:, 0], hi[:, 0], 11),
                        dequantize((p >> 11) & 1023, lo[:, 1], hi[:, 1], 10),
                        dequantize(p & 2047, lo[:, 2], hi[:, 2], 11)], 1)
    sb = arrs["scale_bounds"].astype(np.float64)
    scale = dequantize(arrs["scale"], sb[ci, :3], sb[ci, 3:], 8)
    rot = decode_quaternions(arrs["rot"])
    dlo, dhi = np.array(hdr["dc_range"][0]), np.array(hdr["dc_range"][1])
    f_dc = dequantize(arrs["dc"], dlo, dhi, 8)
    alpha = dequantize(arrs["alpha"], 0.0, 1.0, 8)
    opacity = logit(alpha, eps=0.5 / 255)
    Kr = SH_REST_PER_DEGREE[hdr["sh_degree"]]
    if hdr["sh_mode"] == "8bit":
        r = hdr["sh_range"]
        f_rest = dequantize(arrs["sh"], -r, r, 8)
    elif hdr["sh_mode"] == "vq":
        f_rest = arrs["sh_codebook"].astype(np.float32)[arrs["sh_index"].astype(np.int64)]
    else:
        f_rest = np.zeros((N, 0))
    f32 = lambda a: np.ascontiguousarray(a, dtype=np.float32)
    return GaussianCloud(f32(xyz), f32(f_dc), f32(f_rest).reshape(N, 3, Kr), f32(opacity), f32(scale), f32(rot))


def decode_file(path) -> GaussianCloud:
    with open(path, "rb") as f:
        return decode(f.read())


# ============================================================ erreurs
def reconstruction_errors(ref: GaussianCloud, dec: GaussianCloud):
    """Erreurs attribut par attribut (même ordre de gaussiennes)."""
    ext = float(np.linalg.norm(np.quantile(ref.xyz, 0.99, 0) - np.quantile(ref.xyz, 0.01, 0)))
    dpos = np.linalg.norm(ref.xyz - dec.xyz, axis=1)
    q1, q2 = ref.normalized_rot(), dec.normalized_rot()
    ang = np.degrees(2 * np.arccos(np.clip(np.abs((q1 * q2).sum(1)), 0, 1)))
    out = {
        "pos_rmse_rel_extent": float(np.sqrt((dpos ** 2).mean()) / ext),
        "pos_max_rel_extent": float(dpos.max() / ext),
        "rot_mean_deg": float(ang.mean()), "rot_p99_deg": float(np.quantile(ang, 0.99)),
        "logscale_rmse": float(np.sqrt(((ref.scale - dec.scale) ** 2).mean())),
        "rgb_rmse_255": float(255 * np.sqrt(((ref.rgb - dec.rgb) ** 2).mean())),
        "alpha_rmse_255": float(255 * np.sqrt(((ref.alpha - dec.alpha) ** 2).mean())),
    }
    k = min(ref.f_rest.shape[2], dec.f_rest.shape[2])
    if ref.f_rest.shape[2]:
        R = np.zeros_like(ref.f_rest)
        R[:, :, :k] = dec.f_rest[:, :, :k]
        out["sh_rmse"] = float(np.sqrt(((ref.f_rest - R) ** 2).mean()))
        out["sh_rms_ref"] = float(np.sqrt((ref.f_rest ** 2).mean()))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("encode")
    e.add_argument("input")
    e.add_argument("output")
    e.add_argument("--pos", choices=("16", "11-10-11"), default="16")
    e.add_argument("--sh", choices=("none", "8bit", "vq"), default="vq")
    e.add_argument("--codebook", type=int, default=4096)
    e.add_argument("--sh-zero", type=float, default=0.0, help="seuil d'énergie relative -> SH nuls")
    e.add_argument("--entropy", choices=("lzma", "zlib", "none"), default="lzma")
    e.add_argument("--decoded", help="écrit aussi le PLY décodé (pour visualiser la perte)")
    d = sp.add_parser("decode")
    d.add_argument("input")
    d.add_argument("output")
    args = ap.parse_args()

    if args.cmd == "encode":
        g = load(args.input)
        blob, ref, st = encode(g, args.pos, args.sh, args.codebook, args.sh_zero, args.entropy)
        with open(args.output, "wb") as f:
            f.write(blob)
        src = os.path.getsize(args.input)
        print(f"{human_size(src)} -> {human_size(len(blob))}  (x{src / len(blob):.1f}, "
              f"{st['bytes_per_gaussian']:.2f} o/gaussienne, {st['encode_s']:.1f} s)")
        print("Taille brute par section :", {k: human_size(v) for k, v in st["sections_raw_bytes"].items()})
        dec = decode(blob)
        for k, v in reconstruction_errors(ref, dec).items():
            print(f"  {k:<22} {v:.4g}")
        if args.decoded:
            write_ply(args.decoded, dec)
    else:
        write_ply(args.output, decode_file(args.input))


if __name__ == "__main__":
    main()
