# 5. Guide de bonnes pratiques — capture et optimisation 3DGS pour le web

> Livrable « Synthèse ». Version 0.1 : rédigée à partir de l'état de l'art et de la validation sur scène
> synthétique. **Chaque recommandation chiffrée (marquée ⟨à confirmer⟩) doit être vérifiée sur les
> captures réelles** et mise à jour avec les mesures du chapitre 4.

## En une page

1. **Bien capturer coûte moins cher que bien nettoyer** : exposition verrouillée, pas de flou, 70–80 % de
   recouvrement, couvrir tout ce qui doit être vu.
2. **Limiter le nombre de gaussiennes dès l'entraînement** (profil MCMC / nombre max de splats) quand la
   cible est le web ou le mobile.
3. **Toujours nettoyer** : NaN, α < 1/255, gaussiennes géantes, floaters (peu opaques ET grosses), halo lointain.
   C'est sans perte visible et c'est ce qui a le plus d'effet sur la fluidité.
4. **Élaguer avec un score d'importance**, en cherchant le « coude » qualité/taille (souvent entre 30 et
   60 % de gaussiennes conservées ⟨à confirmer⟩). Avec les poses caméras, préférer le score « views ».
5. **Réduire les SH** selon la scène : degré 0–1 pour une scène mate, garder 2–3 pour les matériaux brillants.
6. **Quantifier** (positions 16 bits relatives à des blocs triés Morton, rotation 32 bits, couleurs 8 bits,
   SH par quantification vectorielle) : ×10 à ×16 quasi sans perte.
7. **Diffuser dans un format compressé reconnu** (compressed.ply / SOG / SPZ / ksplat selon le
   visualiseur), servi avec compression HTTP et cache.
8. **Mesurer** : taille, temps de chargement, FPS (moyen et 1 % low) sur l'appareil cible, PSNR/SSIM
   contre la référence sur des poses fixes. Une optimisation non mesurée n'est pas une optimisation.

## A. Capture

| À faire | À éviter |
|---|---|
| verrouiller exposition / balance des blancs / mise au point | mode auto, HDR, filtres |
| vitesse ≥ 1/250 s, lumière diffuse (ciel couvert, intérieur éclairé uniformément) | soleil direct + ombres dures, contre-jour |
| 3 orbites à 3 hauteurs (objet) ; couronne le long des murs (intérieur) | rotation sur place sans translation |
| 150–300 images nettes, résolution ≤ 1920 px | milliers d'images redondantes |
| extraire les images nettes d'une vidéo (`extract_frames.py`) | garder les images floues |
| scène statique | passants, objets qui bougent, écrans allumés |

Surfaces à risque : vitres, miroirs, métal poli (→ floaters et SH forts), murs blancs uniformes (→ SfM
difficile, grosses gaussiennes), végétation au vent.

## B. Génération

* Noter outil, version, profil, itérations, nombre de gaussiennes, temps, GPU.
* Pour le web : fixer un **budget** de gaussiennes (ex. 1 M pour un ordinateur, 300–500 k pour un mobile
  ⟨à confirmer⟩) plutôt que de tout élaguer après coup.
* Conserver les poses caméras (COLMAP / cameras.json) : elles servent à l'élagage « views » et à la mesure
  de qualité contre les photos.

## C. Chaîne d'optimisation recommandée

```bash
python3 scripts/analyze.py scene.ply --plot histos.png                 # 1. diagnostiquer
python3 scripts/clean.py scene.ply clean.ply --preset medium --report clean.json   # 2. nettoyer
#   → retouches manuelles dans SuperSplat si des floaters subsistent, export PLY
python3 scripts/prune.py clean.ply pruned.ply --keep-ratio 0.5 --cameras sparse/0 --occlusion  # 3. élaguer
python3 scripts/sh_reduce.py pruned.ply sh.ply --degree 2               # 4. SH (selon la scène)
python3 scripts/gsq.py encode sh.ply final.gsq --decoded final_check.ply   # 5. quantifier + mesurer la perte
#   → diffusion : export compressed.ply / SOG depuis SuperSplat, ou .ksplat / .splat selon le visualiseur
```

Règles de réglage :
* changer **un paramètre à la fois** et le mesurer (`pipeline.py` + visualiseur) ;
* garder le PLY nettoyé comme **référence de qualité** de la suite (l'élagage et la quantification sont
  évalués par rapport à lui) ;
* vérifier visuellement les zones à risque (sol, murs, détails fins, objets brillants) en plus des
  métriques globales — un PSNR moyen élevé peut cacher un trou local.

## D. Seuils de décision (premiers repères)

| Métrique (vs référence) | Acceptable | Limite | Inacceptable |
|---|---|---|---|
| PSNR | > 35 dB | 30–35 dB | < 30 dB |
| SSIM | > 0,97 | 0,93–0,97 | < 0,93 |
| FPS (appareil cible) | ≥ 60 (≥ 30 mobile) | 30–60 | < 30 |
| Chargement (4G) | < 3 s | 3–8 s | > 8 s |
| Taille | < 20 Mo | 20–50 Mo | > 50 Mo |

Seuils indicatifs ⟨à confirmer avec l'encadrant et les mesures⟩.

## E. Intégration web

* Choisir le visualiseur selon le format : `gaussian-splats-3d` (Three.js ; PLY, splat, ksplat, spz ;
  SH ≤ 2), PlayCanvas / SuperSplat viewer (compressed.ply, SOG), Spark (Three.js), visualiseurs Babylon.js…
* Activer la compression HTTP (gzip/brotli) pour les formats non compressés, un cache long avec nom
  de fichier versionné, et si possible un **chargement progressif** (afficher les gaussiennes les plus
  importantes d'abord : c'est l'intérêt du tri par importance du format `.splat`).
* Limiter la résolution de rendu sur mobile (`pixelRatio = 1`) : le coût est proportionnel au nombre de
  pixels × surdessin.
* Prévoir un niveau de détail : une version légère chargée d'abord, la version complète ensuite.
