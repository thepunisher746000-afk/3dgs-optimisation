#!/usr/bin/env python3
"""Métriques de qualité image hors-ligne : PSNR, SSIM et (optionnel) LPIPS.

Deux modes :
  1. résultats du visualiseur (cocher « inclure les captures PNG ») :
        python3 scripts/metrics_images.py --bench bench_XXXX.json [--lpips]
     -> compare chaque modèle au premier (référence), pose par pose, et fusionne avec les mesures
        de chargement / FPS dans un tableau Markdown.
  2. deux dossiers d'images de mêmes noms (ex. rendus d'entraînement vs vérité terrain) :
        python3 scripts/metrics_images.py --ref renders_gt/ --test renders_opt/

Dépendances : numpy, Pillow ; LPIPS : torch + lpips (pip install lpips).
"""
import argparse
import base64
import io
import json
import os
import sys

import numpy as np


def load_img(src):
    from PIL import Image
    if isinstance(src, str) and src.startswith("data:"):
        src = io.BytesIO(base64.b64decode(src.split(",", 1)[1]))
    return np.asarray(Image.open(src).convert("RGB"), dtype=np.float64)


def psnr(a, b):
    mse = ((a - b) ** 2).mean()
    return float("inf") if mse == 0 else float(10 * np.log10(255 ** 2 / mse))


def _gauss_blur(x, sigma=1.5, radius=5):
    k = np.exp(-np.arange(-radius, radius + 1) ** 2 / (2 * sigma ** 2))
    k /= k.sum()
    p = np.pad(x, ((radius, radius), (radius, radius)), mode="edge")
    h = sum(k[i] * p[:, i:i + x.shape[1]] for i in range(2 * radius + 1))
    return sum(k[i] * h[i:i + x.shape[0], :] for i in range(2 * radius + 1))


def ssim(a, b):
    """SSIM (Wang et al. 2004), fenêtre gaussienne 11x11 sigma 1.5, moyenne des canaux RGB."""
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    vals = []
    for c in range(3):
        x, y = a[..., c], b[..., c]
        mx, my = _gauss_blur(x), _gauss_blur(y)
        vx = _gauss_blur(x * x) - mx ** 2
        vy = _gauss_blur(y * y) - my ** 2
        cxy = _gauss_blur(x * y) - mx * my
        m = ((2 * mx * my + C1) * (2 * cxy + C2)) / ((mx ** 2 + my ** 2 + C1) * (vx + vy + C2))
        vals.append(m[5:-5, 5:-5].mean())
    return float(np.mean(vals))


class Lpips:
    def __init__(self):
        import lpips
        import torch
        self.torch = torch
        self.net = lpips.LPIPS(net="alex", verbose=False)

    def __call__(self, a, b):
        t = lambda im: self.torch.tensor(im / 127.5 - 1, dtype=self.torch.float32).permute(2, 0, 1)[None]
        with self.torch.no_grad():
            return float(self.net(t(a), t(b)).item())


def compare(refs, tests, lp=None):
    out = {"psnr": [], "ssim": [], "lpips": []}
    for r, t in zip(refs, tests):
        A, B = load_img(r), load_img(t)
        out["psnr"].append(psnr(A, B))
        out["ssim"].append(ssim(A, B))
        if lp:
            out["lpips"].append(lp(A, B))
    return {k: (float(np.mean([v for v in vs if np.isfinite(v)])) if vs else None) for k, vs in out.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench")
    ap.add_argument("--ref")
    ap.add_argument("--test")
    ap.add_argument("--lpips", action="store_true")
    ap.add_argument("--out", help="tableau Markdown de sortie")
    args = ap.parse_args()
    lp = Lpips() if args.lpips else None

    if args.bench:
        data = json.load(open(args.bench))
        res = data["results"]
        if not res[0]["shots"] or not res[0]["shots"][0].get("png"):
            sys.exit("Le JSON ne contient pas les PNG : relancer le benchmark avec la case cochée.")
        ref = [s["png"] for s in res[0]["shots"]]
        lines = [f"Environnement : {data['env']['gpu']} — {data['env']['resolution']} — SH {data['env']['shDegree']}", "",
                 "| Modèle | Taille | Gaussiennes | Chargement total (ms) | FPS moy. | 1% low | PSNR | SSIM | LPIPS |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for r in res:
            m = compare(ref, [s["png"] for s in r["shots"]], lp)
            lines.append(f"| {r['name']} | {r['bytes'] / 2 ** 20:.1f} Mo | {r['splatCount']} | {r['totalMs']:.0f} | "
                         f"{r.get('fpsMean', float('nan')):.1f} | {r.get('fpsLow1', float('nan')):.1f} | "
                         f"{m['psnr']:.2f} | {m['ssim']:.4f} | {m['lpips'] if m['lpips'] is None else round(m['lpips'], 4)} |")
    else:
        names = sorted(f for f in os.listdir(args.ref) if f.lower().endswith((".png", ".jpg", ".jpeg")))
        m = compare([os.path.join(args.ref, n) for n in names], [os.path.join(args.test, n) for n in names], lp)
        lines = [f"{len(names)} images : PSNR {m['psnr']:.2f} dB, SSIM {m['ssim']:.4f}, LPIPS {m['lpips']}"]
    txt = "\n".join(lines)
    print(txt)
    if args.out:
        open(args.out, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
