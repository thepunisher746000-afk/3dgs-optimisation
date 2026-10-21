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
python3 -m http.server 8123
```
puis ouvrir `http://localhost:8123/viewer/` (ou
`http://localhost:8123/viewer/?models=../results/synthetic/C0_original.ply,../results/synthetic/C3_prune50.ply`).

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

