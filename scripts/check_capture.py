#!/usr/bin/env python3
"""Vérifie qu'un jeu de photos est exploitable pour le Gaussian Splatting AVANT de lancer un
entraînement (qui prend des dizaines de minutes et échoue souvent sans message clair).

Contrôles (docs/02_capture_generation.md) :
  * nombre d'images (3DGS : idéalement 100 à 300 ; en dessous de ~50 le modèle sera troué) ;
  * netteté (variance du Laplacien), images floues signalées ;
  * exposition : écarts de luminosité entre images (exposition non verrouillée -> floaters colorés) ;
  * objectif : focale équivalente 35 mm (EXIF) ; ultra grand-angle = forte distorsion ;
  * RECOUVREMENT : points ORB appariés entre paires d'images puis filtrés géométriquement (RANSAC sur
    la matrice fondamentale). Deux images « se voient » au-delà de 50 correspondances fiables. Le graphe
    de ces liens doit être connexe et dense, sinon la reconstruction des poses (SfM) se coupe en morceaux.

    python3 scripts/check_capture.py data/captures/salle
Écrit data/captures/<nom>/check.json et affiche un verdict avec des recommandations.
"""
import argparse
import json
import os
import sys

import numpy as np

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")
LINK = 50  # correspondances fiables minimales pour considérer deux vues comme liées


def exif_focal35(path):
    try:
        from PIL import Image
        ex = Image.open(path).getexif()
        sub = ex.get_ifd(0x8769)
        f35 = sub.get(41989) or ex.get(41989)   # FocalLengthIn35mmFilm
        model = ex.get(272)
        return (int(f35) if f35 else None), (str(model).strip() if model else None)
    except Exception:
        return None, None


def main():
    import cv2
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", help="dossier de capture (contenant images/) ou dossier d'images")
    ap.add_argument("--max-pairs", type=int, default=3000, help="paires testées au plus (voisines d'abord)")
    args = ap.parse_args()

    d = args.capture.rstrip("/")
    img_dir = os.path.join(d, "images") if os.path.isdir(os.path.join(d, "images")) else d
    names = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(IMAGE_EXT))
    n = len(names)
    if n == 0:
        sys.exit(f"aucune image dans {img_dir}")
    print(f"{n} images dans {img_dir}")

    orb = cv2.ORB_create(3000)
    feats, sharp, bright, sizes, focals = [], [], [], [], []
    model = None
    for name in names:
        p = os.path.join(img_dir, name)
        im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        sizes.append(im.shape[::-1])
        s = 1600 / max(im.shape)
        g = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else im
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        bright.append(float(g.mean()))
        feats.append(orb.detectAndCompute(g, None))
        f35, mdl = exif_focal35(p)
        focals.append(f35)
        model = model or mdl

    # paires : toutes si peu d'images, sinon voisines dans l'ordre de prise de vue + échantillon
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if len(pairs) > args.max_pairs:
        near = [(i, j) for i in range(n) for j in range(i + 1, min(n, i + 8))]
        rng = np.random.default_rng(0)
        far = [pairs[k] for k in rng.choice(len(pairs), args.max_pairs - len(near), replace=False)]
        pairs = sorted(set(near + far))
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    links = np.zeros((n, n), int)
    tested = set()

    def match(i, j):
        tested.add((i, j))
        (ki, di), (kj, dj) = feats[i], feats[j]
        if di is None or dj is None:
            return
        good = [a for a, b in (m for m in bf.knnMatch(di, dj, k=2) if len(m) == 2) if a.distance < 0.75 * b.distance]
        if len(good) < 8:
            return
        p1 = np.float32([ki[a.queryIdx].pt for a in good])
        p2 = np.float32([kj[a.trainIdx].pt for a in good])
        _, mask = cv2.findFundamentalMat(p1, p2, cv2.FM_RANSAC, 2.0, 0.99)
        links[i, j] = links[j, i] = int(mask.sum()) if mask is not None else 0

    def components():
        adj = links >= LINK
        comp, seen = [], set()
        for s in range(n):
            if s in seen:
                continue
            stack, cur = [s], []
            seen.add(s)
            while stack:
                u = stack.pop()
                cur.append(u)
                for v in np.flatnonzero(adj[u]):
                    if v not in seen:
                        seen.add(int(v)); stack.append(int(v))
            comp.append(sorted(cur))
        return sorted(comp, key=len, reverse=True), adj

    for i, j in pairs:
        match(i, j)
    comp, adj = components()
    # 2e passe : si l'échantillonnage laisse plusieurs groupes, on teste TOUTES les paires entre groupes
    # différents (une liaison a pu échapper à l'échantillon) avant de conclure qu'ils sont séparés.
    if len(comp) > 1:
        label = np.empty(n, int)
        for k, c in enumerate(comp):
            label[c] = k
        bridge = [(i, j) for i in range(n) for j in range(i + 1, n) if label[i] != label[j] and (i, j) not in tested]
        if len(bridge) > 4 * args.max_pairs:
            rng = np.random.default_rng(1)
            bridge = [bridge[k] for k in rng.choice(len(bridge), 4 * args.max_pairs, replace=False)]
        print(f"{len(comp)} groupes après échantillonnage : test de {len(bridge)} paires supplémentaires entre groupes…")
        for i, j in bridge:
            match(i, j)
        comp, adj = components()
    pairs = sorted(tested)
    degree = adj.sum(1)
    med_sharp = float(np.median(sharp))
    blurry = [names[i] for i in range(n) if sharp[i] < 0.3 * med_sharp]
    isolated = [names[i] for i in range(n) if degree[i] == 0]
    f35 = [f for f in focals if f]

    issues, advice = [], []
    if n < 20:
        issues.append(("critique", f"{n} images seulement : le Gaussian Splatting en demande au moins 50, idéalement 100 à 300."))
        advice.append("Filmer une vidéo lente (1 à 2 min, 4K) en faisant le tour de la pièce, puis « Extraire les images » "
                      "(2 à 3 images/s) : on obtient facilement 150 à 300 vues.")
    elif n < 80:
        issues.append(("attention", f"{n} images : peu pour une pièce entière (viser 150 à 300)."))
    if len(comp) > 1:
        issues.append(("critique" if len(comp[0]) < 0.8 * n else "attention",
                       f"Les photos forment {len(comp)} groupes sans lien entre eux (le plus grand : {len(comp[0])} images) : "
                       "la reconstruction des poses ne pourra pas tout assembler."))
        advice.append("Ajouter des vues intermédiaires entre les groupes : chaque photo doit partager 70 à 80 % de son contenu "
                      "avec la précédente (pas de rotation de plus de 15-20° d'une vue à l'autre).")
    if isolated:
        issues.append(("attention", f"{len(isolated)} image(s) sans aucune voisine fiable : {', '.join(isolated[:5])}"))
    if blurry:
        issues.append(("attention", f"{len(blurry)} image(s) floue(s) : {', '.join(blurry[:5])}"))
        advice.append("Supprimer ou refaire les images floues (vitesse d'obturation ≥ 1/250 s, mouvement lent).")
    if np.std(bright) > 0.12 * np.mean(bright):
        issues.append(("attention", f"Luminosité variable d'une image à l'autre (écart-type {np.std(bright):.0f}/255) : "
                                    "exposition probablement automatique."))
        advice.append("Verrouiller l'exposition et la balance des blancs (appui long sur l'écran / mode Pro).")
    if f35 and min(f35) < 20:
        issues.append(("attention", f"Objectif ultra grand-angle (≈ {min(f35)} mm équivalent) : forte distorsion en bord d'image."))
        advice.append("Utiliser l'objectif principal (≈ 24-28 mm) plutôt que l'ultra grand-angle, et faire plus de vues.")
    if max(max(s) for s in sizes) > 2000:
        advice.append("Les images seront réduites à ~1600-2000 px pour l'entraînement (plus de pixels = plus lent, peu de gain).")
    level = "critique" if any(i[0] == "critique" for i in issues) else "attention" if issues else "ok"
    verdict = {"ok": "Capture exploitable : lancer la génération du modèle.",
               "attention": "Capture utilisable, mais le modèle risque d'être incomplet ou de contenir des floaters.",
               "critique": "Capture insuffisante pour un modèle 3DGS de qualité : à refaire ou compléter avant d'entraîner."}[level]

    report = {"images": n, "folder": img_dir, "camera": model, "focal35": sorted(set(f35)),
              "resolution": [int(x) for x in max(sizes, key=lambda s: s[0] * s[1])],
              "sharpness": dict(zip(names, [round(x, 1) for x in sharp])), "blurry": blurry,
              "brightness_mean": round(float(np.mean(bright)), 1), "brightness_std": round(float(np.std(bright)), 1),
              "pairs_tested": len(pairs), "linked_pairs": int(np.triu(adj, 1).sum()),
              "components": [[names[i] for i in c] for c in comp], "isolated": isolated,
              "links": {f"{names[i]}|{names[j]}": int(links[i, j]) for i, j in pairs if links[i, j] > 0},
              "level": level, "verdict": verdict, "issues": [{"level": a, "text": b} for a, b in issues], "advice": advice}
    out = os.path.join(d, "check.json") if img_dir != d else os.path.join(d, "..", "check.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)

    print(f"Appareil : {model or '?'} ; focale 35 mm : {sorted(set(f35)) or '?'} ; résolution max {report['resolution']}")
    print(f"Paires testées {len(pairs)}, liées (≥ {LINK} correspondances fiables) : {report['linked_pairs']} ; "
          f"groupes : {[len(c) for c in comp]}")
    print(f"\nVERDICT ({level}) : {verdict}")
    for a, b in issues:
        print(f"  [{a}] {b}")
    if advice:
        print("Recommandations :")
        for a in advice:
            print(f"  - {a}")
    print(f"\nRapport : {out}")


if __name__ == "__main__":
    main()
