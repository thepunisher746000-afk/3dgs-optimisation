#!/usr/bin/env python3
"""Extraction des images nettes d'une vidéo de capture, avant génération 3DGS (PostShot, COLMAP, ...).

Principe (docs/02_capture_generation.md, §3) : on découpe la vidéo en fenêtres de W images et on
garde, dans chaque fenêtre, l'image la plus nette selon la variance du Laplacien
(mesure de netteté classique : une image floue a peu de hautes fréquences -> variance faible).
On rejette aussi les fenêtres dont la meilleure image reste sous un seuil absolu.

    python3 scripts/extract_frames.py capture.mp4 frames/ --fps 3 --max-side 1920
Dépendance : opencv-python.
"""
import argparse
import os

import numpy as np


def sharpness(gray, cv2):
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--fps", type=float, default=3.0, help="images conservées par seconde de vidéo")
    ap.add_argument("--max-side", type=int, default=1920, help="redimensionne le plus grand côté (0 = non)")
    ap.add_argument("--min-sharpness", type=float, default=0.0, help="seuil absolu (0 = auto : 30 %% de la médiane)")
    args = ap.parse_args()
    import cv2

    cap = cv2.VideoCapture(args.video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    win = max(1, int(round(src_fps / args.fps)))
    os.makedirs(args.out_dir, exist_ok=True)
    best, best_s, kept, scores, i = None, -1.0, [], [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=0.5, fy=0.5)  # plus rapide, classement inchangé
        s = sharpness(g, cv2)
        if s > best_s:
            best, best_s = frame, s
        i += 1
        if i % win == 0:
            kept.append((best, best_s)); scores.append(best_s)
            best, best_s = None, -1.0
    if best is not None:
        kept.append((best, best_s)); scores.append(best_s)
    thr = args.min_sharpness or 0.3 * float(np.median(scores))
    n = 0
    for frame, s in kept:
        if s < thr:
            continue
        if args.max_side:
            h, w = frame.shape[:2]
            f = args.max_side / max(h, w)
            if f < 1:
                frame = cv2.resize(frame, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(args.out_dir, f"frame_{n:05d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        n += 1
    print(f"{i} images lues, {len(kept)} fenêtres, {n} images gardées (seuil netteté {thr:.1f}) -> {args.out_dir}")


if __name__ == "__main__":
    main()
