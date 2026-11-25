# 4. Intégration web et protocole de mesure

> Livrable « Intégration et mesures » : intégrer les modèles optimisés dans un visualiseur web et mesurer
> l'impact de chaque optimisation sur **le temps de chargement**, **la fluidité** et **la qualité visuelle**.

## 4.1 Le visualiseur de mesure (`viewer/`)

* **Pile technique** : Three.js 0.167 + `@mkkellogg/gaussian-splats-3d` 0.4.7 (chargés par *import map*
  depuis un CDN, aucune compilation). Formats lus : PLY, `.splat`, `.ksplat`, `.spz`.
* **Boucle de rendu pilotée par nous** (`selfDrivenMode: false`) : chaque trame appelle
  `viewer.update(); viewer.render()` dans notre `requestAnimationFrame`, ce qui permet de mesurer chaque
  intervalle entre trames et d'imposer exactement la même trajectoire de caméra à tous les modèles.
* **Réglages fixés pour la comparabilité** : `pixelRatio = 1`, résolution fixe (1280×720 par défaut),
  fond noir, `sceneRevealMode: Instant` (pas de fondu), degré SH choisi (0–2), tri sur CPU sans mémoire
  partagée (pas besoin d'en-têtes COOP/COEP).

Lancement :
```bash
cd 3dgs-optimisation
python3 app.py
```
puis ouvrir `http://localhost:8000` → onglet **Visualiseur** (ou, depuis **Résultats**, cocher des versions
et cliquer « Comparer la sélection »). Les mesures d'un benchmark sont enregistrées automatiquement dans
`results/<scène>/bench_*.json` et affichées dans l'onglet Résultats.

### Déroulement d'un benchmark
1. Liste de modèles : **le premier est la référence** de qualité (en général C0 ou C2 nettoyé).
2. Poses de mesure : vues ajoutées à la main (« + Vue courante »), orbite automatique, ou fichier
   `poses.json` importé — **réutiliser le même fichier pour toutes les sessions**.
3. Pour chaque modèle :
   1. chargement chronométré (voir 4.2) ;
   2. parcours de la boucle de poses pendant *D* secondes (interpolation lissée), enregistrement des
      intervalles entre trames ;
   3. pour chaque pose : stabilisation (attente de la fin du tri asynchrone), capture de l'image, calcul
      PSNR/SSIM par rapport à la capture de la référence à la même pose.
4. Export JSON (environnement, GPU, résolution, poses, mesures, vignettes, et en option les PNG complets).

## 4.2 Métriques

### Taille
* octets du fichier, **octets par gaussienne**, facteur de compression par rapport au PLY d'origine ;
* taille après gzip (`pipeline.py --gzip`) = ce qui transite réellement si le serveur compresse en HTTP.
  Observation : gzip ne gagne que ~11 % sur un PLY (flottants bruités) mais ~33 % sur un `.splat`.

### Chargement (visualiseur)
| Mesure | Définition | Dépend de |
|---|---|---|
| `readMs` | lecture / téléchargement du fichier complet | taille, réseau |
| `decodeUploadMs` | parsing, conversion interne, envoi des textures au GPU | N, format |
| `firstFrameMs` | jusqu'à la première image triée affichée | N, tri |
| `totalMs` | somme | — |

Pour simuler le réseau : servir les fichiers en HTTP (mode URL, pas fichier local) et utiliser le
*throttling* des DevTools (« Fast 4G », « Slow 4G »), cache désactivé.

### Fluidité
À partir des intervalles $\Delta t_i$ entre trames pendant le parcours :
* **FPS moyen** $= 1000 / \overline{\Delta t}$ ;
* **temps de trame médian, p95, p99** (ms) : les saccades se voient dans p95/p99, pas dans la moyenne ;
* **« 1 % low »** $= 1000 / \text{moyenne des 1 % plus longues trames}$.

⚠️ Le FPS est plafonné par la synchronisation verticale (60 Hz, parfois 30 Hz dans une fenêtre
intégrée). Si tous les modèles atteignent le plafond, comparer sur un appareil plus faible (portable
sans GPU dédié, smartphone), à plus haute résolution (1920×1080), ou lancer Chrome avec
`--disable-gpu-vsync --disable-frame-rate-limit` pour lever le plafond.

### Qualité visuelle
Calculées pose par pose entre le rendu du modèle testé et celui de la référence (même pose, même résolution) :
* **PSNR** $= 10 \log_{10}(255^2 / \text{MSE})$ en dB ; > 40 dB : différence invisible, 30–40 : faible,
  < 25 : dégradation nette ;
* **SSIM** (Wang et al. 2004, fenêtre gaussienne 11×11, σ = 1,5, moyenne RGB) ∈ [0, 1] : sensible à la
  structure (trous, flou) ;
* **LPIPS** (Zhang et al. 2018) hors-ligne via `scripts/metrics_images.py --bench bench.json --lpips` :
  distance perceptuelle apprise, la plus proche du jugement humain.

Deux références possibles :
1. **fidélité au modèle original** (ce que mesure le visualiseur) : isole l'effet de l'optimisation ;
2. **fidélité aux photos réelles** sur des vues de test non utilisées à l'entraînement (nécessite les
   poses : rendus via gsplat/Nerfstudio puis `metrics_images.py --ref photos/ --test rendus/`) : c'est la
   métrique des articles ; à faire au moins pour C0 et la configuration finale.

## 4.3 Protocole expérimental

* Même machine, même navigateur (version notée), même résolution, onglet au premier plan, pas d'autre
  application lourde, portable **sur secteur**.
* 3 répétitions du benchmark ; retenir la **médiane** ; noter l'écart.
* Au moins deux appareils : PC de développement + un appareil « cible » (portable à GPU intégré ou
  smartphone via `chrome://inspect`).
* Matrice de configurations : `configs/default.json` (C0 à C7), à ajuster après les premiers résultats.

| Config | Étapes | Question étudiée |
|---|---|---|
| C0 | original (sans normales) | référence |
| C1 / C2 | nettoyage léger / moyen | gain « gratuit » du nettoyage ? |
| C3a / C3b | + élagage à 75 %, score proxy / score views + occultation | quel score d'importance ? |
| C4 | C3b + SH degré 1 | perte des reflets acceptable ? |
| C5 | C3b + GSQ (VQ des SH) | quantification quasi sans perte ? |
| C6 / C7 | élagage 50 % / 35 % + compression | jusqu'où peut-on aller ? |

## 4.3bis Benchmark automatique des algorithmes (`scripts/benchmark.py`, onglet Benchmark)

Le visualiseur web mesure ce que voit l'utilisateur, mais ses temps dépendent du navigateur : un onglet
caché suspend le rendu. Pour **classer les algorithmes** de façon reproductible, le benchmark rend
chaque variante avec un **rasteriseur de référence sur CPU** (`scripts/render.py`). Il reproduit le
rasteriseur de 3DGS : projection EWA, harmoniques sphériques jusqu'au degré 3, et composition alpha exacte
par tri des fragments (pixel, profondeur).

Protocole :
1. **Référence** : la scène d'entrée après nettoyage moyen. Les floaters y sont considérés comme des erreurs.
2. **Variantes** (`configs/benchmark.json`, 25 variantes en 7 familles) : référence, nettoyage, élagage,
   couleurs SH, quantification, combinaisons, formats existants. Chaque variante est traitée, **exportée
   puis relue**, donc la perte de compression est comptée.
3. **Vues de test distinctes des caméras du score d'élagage** : plus proches, décalées en azimut, sur deux
   hauteurs. Sinon le score « views » serait évalué sur les vues qu'il a optimisées : c'est le même principe
   que la séparation apprentissage / test.
4. **Mesures** : taille, facteur de compression, PSNR et SSIM moyens et sur la pire vue, et **surdessin**
   (fragments composés par pixel). Le surdessin est un indicateur du coût d'affichage indépendant du GPU :
   chaque fragment est un mélange alpha que la carte graphique doit faire.
5. **Analyse** :
   - front de **Pareto** taille/qualité (variantes qu'aucune autre ne bat à la fois en taille et en qualité) ;
   - plus petit fichier à PSNR ≥ 35 dB (« invisible ») et ≥ 30 dB (« acceptable ») ;
   - pour chaque famille, l'**efficacité** = dB perdus chaque fois que la taille est divisée par 2.
     Plus c'est bas, plus l'algorithme est « rentable ».

Formats existants : `.splat` (antimatter15) est intégré. Les formats PlayCanvas (compressed.ply, SOG) sont
mesurés via `splat-transform` s'il est installé (`npm install -g @playcanvas/splat-transform`) ; sinon ces
variantes sont marquées « ignorées ».

**Comparaison avec les méthodes publiées** : l'onglet Benchmark reprend le tableau 1 de HAC
([Chen et al., arXiv:2403.14530](https://arxiv.org/abs/2403.14530)), soit 3DGS, LightGaussian,
Compact 3DGS, Compressed3D, EAGLES, Self-Organizing Gaussians, Compact3D et HAC, sur Mip-NeRF360 et
Tanks & Temples. Ces méthodes **ré-entraînent** le modèle et sont évaluées contre les photos réelles, alors
que nos variantes sont des post-traitements évalués contre le modèle de départ. Les facteurs de
compression se comparent ; les PSNR non. Pour une comparaison directe, il faut lancer notre benchmark sur
un modèle 3DGS pré-entraîné d'une de ces scènes.

### Résultats du benchmark sur la scène de test (300 000 gaussiennes, 6 vues 400×300, 14 min)

| Famille | Variante | Taille | ÷ entrée (71 Mo) | PSNR moy. (pire vue) | Surdessin |
|---|---|---|---|---|---|
| Référence | original (floaters, halo) | 67,5 Mo | 1,1 | 9,4 dB (8,8) | 209,5 |
| Référence | nettoyage moyen | 60,8 Mo | 1,2 | référence | 30,2 |
| Élagage | proxy 75 % | 45,6 Mo | 1,6 | 31,2 dB (30,6) | 25,1 |
| Élagage | views + occultation 75 % | 45,6 Mo | 1,6 | **38,4 dB** (35,7) | 25,4 |
| Élagage | views 50 % / + compensation | 30,4 Mo | 2,3 | 32,7 → **34,1 dB** | 23,0 |
| Élagage | views 35 % / + compensation | 21,3 Mo | 3,3 | 28,2 → **31,3 dB** | 21,0 |
| Couleurs | SH degré 1 / degré 0 | 23,7 / 14,4 Mo | 3,0 / 4,9 | 48,4 / 41,0 dB | 30,2 |
| Quantification | GSQ 8 bits / VQ / VQ compact | 8,0 / 3,5 / 2,5 Mo | 8,8 / 20,3 / **28,1** | ≥ 50 / 45,1 / 44,0 dB | 30,2 |
| Combinaison | views 75 % + compensation + GSQ | 2,3 Mo | **30,4** | 38,1 dB (36,8) | 25,4 |
| Combinaison | views 35 % + compensation + GSQ | 1,1 Mo | **64,6** | 31,1 dB (29,3) | 21,0 |
| Format existant | .splat (antimatter15) | 8,2 Mo | 8,6 | 41,0 dB | 30,2 |

Les formats PlayCanvas ont été ignorés : splat-transform n'était pas installé.

**Ce qu'on en tire :**
1. **La quantification est de loin la plus rentable** : ×28 sur la taille pour 44 dB, perte invisible.
   C'est elle qui fait l'essentiel de la compression. Elle bat aussi le format `.splat` existant à taille
   égale : 8 Mo à ≥ 50 dB pour GSQ 8 bits, contre 8,2 Mo à 41 dB pour `.splat`, qui perd les reflets.
2. **Les SH se réduisent presque gratuitement** jusqu'au degré 1 (×3, 48 dB) sur une scène peu brillante.
3. **L'élagage est la famille la moins rentable en taille** : environ 9,5 dB perdus chaque fois que la taille
   est divisée par 2. Il sert surtout à la fluidité. Le score views + occultation est nettement meilleur que
   le proxy (+7 dB à 75 %), et la compensation ajoute +1,5 à +3 dB.
4. **Le nettoyage divise le coût d'affichage par 7** (210 → 30 fragments/pixel). C'est l'étape qui rend le
   modèle fluide, et elle est quasi gratuite.
5. **Meilleurs compromis** (front de Pareto) : GSQ 8 bits, GSQ VQ, puis views 75 % + GSQ (2,3 Mo, 38 dB),
   views 50 % + SH1 + GSQ (1,4 Mo, 34 dB) et views 35 % + GSQ (1,1 Mo, 31 dB).

À refaire sur les captures réelles, dont la redondance diffère. Comparés aux méthodes publiées sur
Mip-NeRF360 (÷15 à ÷49 par rapport à 3DGS d'après le tableau 1 de HAC), les facteurs obtenus ici sans
ré-entraînement sont du même ordre ; la qualité n'est pas comparable directement (cf. ci-dessus).

### Résultats sur une vraie capture : salle A014

Modèle : 165 photos (Nothing Phone 2a, 14 mm), 159 gardées après vérification, 80 placées par COLMAP
(sur CPU). Entraînement nerfstudio splatfacto de 7 000 itérations (GTX 1650 Ti, environ 40 min au total) :
517 513 gaussiennes, 122 Mo. Rendu depuis les poses des photos : 22 à 27 dB **par rapport aux photos réelles**.

Benchmark (suite `configs/benchmark_reel.json`) :
- 6 vues de test = vraies photos ; ces poses sont exclues du score d'élagage ;
- référence = le modèle original, car une vraie capture n'a pas de version « sans défauts » ;
- familles appliquées après un nettoyage léger.

| Famille | Variante | Taille | ÷ original | PSNR moy. (pire vue) |
|---|---|---|---|---|
| Nettoyage | moyen / agressif | 103 / 90 Mo | 1,2 / 1,4 | 35,4 (27,1) / 24,7 (17,7) |
| Élagage | proxy 75 % / views 75 % | 87 Mo | 1,4 | 32,4 (26,4) / **36,1 (30,6)** |
| Élagage | views 50 % / + compensation | 58 Mo | 2,1 | 29,0 → 31,2 (27,0) |
| Couleurs | SH 2 / 1 / 0 | 75 / 45 / 28 Mo | 1,6 / 2,7 / 4,4 | 39,3 / 34,4 / 31,8 |
| Quantification | GSQ 8 bits / VQ / VQ compact | 23 / 8,6 / **7,1 Mo** | 5,3 / 14,3 / **17,2** | ≥ 50 / 41,4 / **39,4 (38,1)** |
| Combinaison | views 75 % + compensation + GSQ | 6,5 Mo | 18,8 | 35,9 (30,9) |
| Format existant | .splat | 15,8 Mo | 7,8 | 31,6 |

**Ce que la vraie scène change par rapport à la scène de test :**
1. **Le nettoyage « moyen » est néfaste** : 27 dB sur la pire vue. Sur un modèle nerfstudio, les grandes
   gaussiennes semi-transparentes forment les murs et le plafond blancs, pas des floaters. Le nettoyage ne
   réduit le surdessin que de 20 % (54 → 45). Sur une vraie capture, s'en tenir au nettoyage **léger** et
   retoucher les vrais floaters à la main (SuperSplat), ou recalibrer les seuils par scène.
2. **L'élagage coûte plus cher** : 36 dB à 75 % (30,6 dB sur la pire vue), contre 38 dB sur la scène de
   test. Le modèle court (7 000 itérations) est peu redondant. Le score views + occultation reste nettement
   meilleur que le proxy (+3,7 dB), et la compensation ajoute environ 2 dB.
3. **Les reflets (SH) comptent** : le degré 1 perd 15 dB de marge (34,4 dB, contre 48 sur la scène de test).
   Le format `.splat`, qui supprime les SH, plafonne donc à 31,6 dB.
4. **La quantification reste la méthode reine** : ÷17 à 39,4 dB sans toucher au nombre de gaussiennes.
   C'est le meilleur compromis à qualité quasi invisible (7,1 Mo au lieu de 122 Mo).

Recommandation pour cette scène : **GSQ VQ compact seul** (7,1 Mo, ÷17, 39 dB) si la qualité prime ;
**élagage views 75 % + compensation + GSQ** (6,5 Mo, ÷19, 36 dB) si la fluidité compte aussi (−5 % de
surdessin seulement, gain faible ici).

## 4.4 Premiers résultats (scène synthétique de validation)

Scène générée par `scripts/make_synthetic.py` (200 000 gaussiennes, degré SH 3) dont on connaît la
composition : contenu visible (sol, sphère brillante, cube), **20 % de gaussiennes cachées** (intérieur des
objets, sous le sol — redondance comparable à celle de la densification), et des défauts : 4,5 % de
gaussiennes quasi transparentes, 3,5 % de floaters, 2 % de halo lointain, 5 NaN.
Ces chiffres **valident la chaîne** ; ils ne remplacent pas les mesures sur les vraies captures.

### a) Nettoyage (`clean.py --preset medium`)

| Filtre | Retirées | Ce qui était visé |
|---|---|---|
| finite | 5 | les 5 NaN injectés ✔ |
| opacity (α < 1/255) | 9 000 | les 9 000 transparentes ✔ |
| scale (> 30 × médiane) | 3 999 | les 4 000 points du halo ✔ |
| floaters (α < 0,2 et > 5 × médiane) | 6 986 | les 7 000 floaters ✔ |
| autocrop / density | 0 / 14 | — (déjà nettoyé) |

Tous les défauts sont retirés sans toucher au contenu. Sans le filtre « floaters » (première version),
les floaters passaient à travers les filtres « opacité » et « taille » pris séparément : c'est la
**combinaison** des deux critères qui les caractérise.

### b) Élagage : quel score ? (fraction conservée par catégorie, 80 % des gaussiennes gardées)

| Score | Sol | Sphère | Cube | Gaussiennes cachées |
|---|---|---|---|---|
| proxy (opacité × volume^0,1) | 0,64 | 0,91 | 0,90 | 0,93 |
| views, 32 caméras en orbite, sans occultation | 0,60 | 0,95 | 0,97 | 0,93 |
| **views + occultation** | **0,92** | **0,98** | **1,00** | **0,28** |

Tendance identique à 60 % conservés (cachées : 0,82 / 0,83 / 0,16). Sans test d'occultation, aucun
score ne distingue une gaussienne cachée d'une visible : on supprime du sol visible pour garder
l'intérieur des objets. Le z-buffer grossier suffit à inverser la tendance. ⇒ **Utiliser les poses
caméras et l'occultation dès qu'elles sont disponibles.**
Revers observé dans une première version de la scène *sans* redondance : chaque gaussienne était utile,
et tout élagage de 50 % créait des trous (PSNR ≈ 22 dB) ; le score views (pondéré par $1/z^2$) y était
même pire que le proxy en vidant le centre du sol, loin des caméras. Le taux d'élagage acceptable dépend
donc directement de la redondance réelle du modèle : il faut le déterminer **par scène** (courbe PSNR / taux).

### c) Taille (`pipeline.py`, configurations de `configs/default.json`)

| Config | Gaussiennes | SH | Fichier | Taille | × PLY d'origine (47,2 Mo) |
|---|---|---|---|---|---|
| C0 | 200 000 | 3 | PLY | 45,0 Mo | 1,05 (normales retirées) |
| C2 nettoyage moyen | 179 996 | 3 | PLY / .splat | 40,5 / 5,5 Mo | 1,17 / 8,6 |
| C3b + élagage 75 % views | 134 997 | 3 | PLY / .splat | 30,4 / 4,1 Mo | 1,56 / 11,5 |
| C4 + SH degré 1 | 134 997 | 1 | PLY | 11,8 Mo | 4,0 |
| C5 + GSQ (VQ 4096) | 134 997 | 3 | .gsq | 1,8 Mo | **26,6** |
| C6 élagage 50 % + SH1 + GSQ 8 bits | 89 998 | 1 | .gsq | 1,4 Mo | 34,9 |
| C7 élagage 35 % + GSQ VQ + SH adaptatifs | 62 999 | 3 | .gsq | 0,98 Mo | 49,6 |

Erreurs de reconstruction GSQ (C5) : position RMS $5\cdot10^{-7}$ × taille de la scène, rotation 0,11°
en moyenne, couleur 0,23/255 RMS, opacité 0,29/255 RMS, SH RMS 0,029 pour une amplitude RMS de 0,052
(c'est la VQ des SH qui concentre la perte). gzip ne réduit le PLY que de 10 % (flottants bruités) mais le
`.splat` de 27 à 31 %.

### d) Visualiseur

Mesures faites sur une **version précédente** de la scène synthétique (sans gaussiennes cachées, sans
filtre « floaters ») — Intel UHD Graphics, 1280×720, SH degré 2, fenêtre plafonnée à 30 Hz :

| Modèle | Taille | Gaussiennes | FPS moy. | 1 % low | PSNR (dB) | SSIM |
|---|---|---|---|---|---|---|
| original (floaters + halo) | 47,3 Mo | 200 000 | **0,7** | — | — | — |
| nettoyage moyen (halo retiré) | 41,5 Mo | 184 251 | 30,0 | — | — | — |
| nettoyé + élagué 50 % (réf. qualité) | 20,7 Mo | 92 126 | 30,0 | 29,8 | réf. | réf. |
| même modèle, GSQ VQ (décodé) | 1,3 Mo* | 92 126 | 30,0 | 28,0 | **45,3** | 0,993 |
| même modèle, `.splat` (SH perdus, 8 bits) | 2,8 Mo | 92 126 | 30,0 | 29,8 | 40,7 | 0,983 |
| élagage 30 % + SH1 + GSQ | 0,84 Mo* | 55 275 | 30,0 | 29,8 | 22,9 | 0,893 |

\* taille du `.gsq` ; le visualiseur charge sa version décodée en PLY.

**Lecture** :
1. Le passage de 0,7 à 30 FPS vient du **nettoyage** (retrait du halo : quelques milliers de gaussiennes
   géantes couvrant tout l'écran), pas de la réduction du nombre de gaussiennes : sur GPU web, le
   **surdessin** coûte plus que le nombre.
2. La quantification + VQ divise la taille par 16 pour une différence invisible (45 dB, SSIM 0,993) ;
   le `.splat` est plus simple mais perd les SH (40,7 dB).
3. Un élagage trop fort crée des trous (22,9 dB).

⏳ **À refaire** sur la scène actuelle et sur les captures réelles (le benchmark s'exécute en une
commande, cf. 4.1 ; garder l'onglet visible au premier plan pendant la mesure : un onglet masqué
suspend `requestAnimationFrame` et fausse le FPS).

