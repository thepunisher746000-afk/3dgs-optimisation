# Évaluation et optimisation du 3D Gaussian Splatting pour la capture d'environnements

Projet 6 — LIS / G-Mod (encadrant : S. Mavromatis). Version 0.1.

Le 3DGS reconstruit des scènes réelles avec un réalisme photographique, mais les fichiers produits
(≈ 250 octets par gaussienne, souvent plusieurs millions de gaussiennes) sont trop lourds pour le web et
le mobile. Ce dépôt contient **la chaîne complète** pour capturer, nettoyer, élaguer, compresser et
mesurer des modèles 3DGS, ainsi que **le dossier technique** qui détaille les méthodes.

## Contenu

```text
3dgs-optimisation/
├── docs/                         dossier technique (algorithmes et méthodes détaillés)
│   ├── 01_fondements_3dgs.md        représentation, rendu, entraînement, pourquoi c'est lourd
│   ├── 02_capture_generation.md     protocole de capture, outils (PostShot, Polycam, Brush…)
│   ├── 03_optimisation.md           ★ nettoyage, élagage, SH, quantification, codage — formules et algorithmes
│   ├── 04_integration_mesures.md    visualiseur, métriques, protocole, premiers résultats
│   ├── 05_guide_bonnes_pratiques.md synthèse (livrable final, v0.1)
│   └── 06_plan_de_travail.md        planning, risques, extensions
├── scripts/                      outils Python (numpy ; scipy/pillow/opencv optionnels)
│   ├── gsply.py                     lecture/écriture PLY 3DGS et .splat
│   ├── analyze.py                   statistiques et diagnostic d'un modèle
│   ├── clean.py                     nettoyage (NaN, opacité, échelle, floaters, recadrage, SOR, densité)
│   ├── prune.py                     élagage par importance (proxy ou par vues caméras + occultation)
│   ├── sh_reduce.py                 réduction des harmoniques sphériques
│   ├── gsq.py                       codec expérimental : Morton + quantification + VQ k-means + LZMA
│   ├── pipeline.py                  applique une matrice de configurations, produit les tableaux
│   ├── metrics_images.py            PSNR / SSIM / LPIPS hors-ligne
│   ├── extract_frames.py            extraction des images nettes d'une vidéo de capture
│   └── make_synthetic.py            scène de test avec défauts connus
├── viewer/                       banc de mesure web (Three.js + gaussian-splats-3d)
├── configs/default.json          configurations C0…C7 testées par pipeline.py
├── data/                         captures et modèles (non versionnés)
└── results/                      sorties de pipeline.py et du visualiseur
```

## Démarrage rapide

```bash
cd 3dgs-optimisation
pip install -r requirements.txt            # numpy suffit pour la chaîne principale

# 1. Valider la chaîne sur la scène synthétique
python3 scripts/make_synthetic.py data/synthetic.ply
python3 scripts/analyze.py data/synthetic.ply
python3 scripts/pipeline.py data/synthetic.ply --out results/synthetic --config configs/default.json --gzip

# 2. Mesurer dans le navigateur
python3 -m http.server 8123
#    → http://localhost:8123/viewer/?models=../results/synthetic/C2_clean_medium.ply,../results/synthetic/C5_prune50_gsq_vq.gsq.ply
#    → « Lancer le benchmark », puis « Télécharger résultats JSON »

# 3. Sur une vraie capture (PLY exporté par PostShot / Polycam / Brush…)
python3 scripts/pipeline.py data/sceneA/sceneA.ply --out results/sceneA --config configs/default.json --gzip
```

## Premiers résultats (scène synthétique, 200 000 gaussiennes)

| Étape | Taille | Facteur | Observation |
|---|---|---|---|
| PLY d'origine | 47,2 Mo | ×1 | 0,7 FPS (GPU intégré) |
| Nettoyage moyen | 40,5 Mo | ×1,2 | 100 % des défauts injectés retirés, contenu intact ; **30 FPS** |
| + élagage 75 % (vues + occultation) | 30,4 Mo | ×1,6 | retire en priorité les gaussiennes cachées |
| + quantification GSQ (VQ des SH) | 1,8 Mo | **×27** | quantification seule : PSNR ≈ 45 dB, SSIM 0,993 |
| élagage 35 % + GSQ | 0,98 Mo | ×50 | risque de trous : à valider par scène |

Les mesures navigateur proviennent d'une version précédente de la scène ; détails, protocole et limites :
[docs/04_integration_mesures.md](docs/04_integration_mesures.md).

## Ce qui reste à faire

Capturer les deux scènes réelles, refaire toutes les mesures dessus, comparer aux formats existants
(compressed.ply, SOG, SPZ, ksplat) et finaliser le guide — voir [docs/06_plan_de_travail.md](docs/06_plan_de_travail.md).
