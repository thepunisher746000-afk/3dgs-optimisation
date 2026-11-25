# 2. Capture et génération du modèle 3DGS

> Livrable « Capture et Génération » : capturer un environnement réel et produire un modèle 3DGS de
> référence (le « C0 » de toutes les mesures). La qualité de la capture conditionne tout le reste : un
> modèle bien capturé contient moins de floaters et se compresse mieux.

## 2.1 Choix de la scène

Prévoir **deux scènes** pour que les conclusions ne dépendent pas d'un cas particulier :

| Scène | Exemple | Intérêt pour l'étude |
|---|---|---|
| A — objet / extérieur, capture « autour » | statue, voiture, façade, cour du labo | cas favorable, orbites faciles, fond lointain (halo à nettoyer) |
| B — intérieur, capture « depuis l'intérieur » | salle de TP, bureau | cas difficile : murs uniformes, fenêtres, reflets, beaucoup de floaters |

Éviter pour une première capture : surfaces miroirs/vitres, objets fins (grillages), personnes qui passent,
éclairage qui change (nuages), surfaces sans texture.

## 2.2 Protocole de prise de vue

**Réglages de l'appareil (photo ou smartphone)**
* Exposition, balance des blancs et mise au point **verrouillées** (AE/AF lock) : le 3DGS suppose une
  scène photométriquement constante ; des variations d'exposition créent des floaters colorés.
* Vitesse d'obturation rapide (≥ 1/250 s en photo, ou bonne lumière en vidéo) pour éviter le flou de bougé.
* Pas de HDR automatique, pas de stabilisation numérique agressive (elle déforme l'image), objectif
  « grand-angle » principal plutôt qu'ultra grand-angle (distorsion).
* Vidéo : 4K à 30 ou 60 im/s, mouvement lent et régulier.

**Trajectoire**
* Scène A : 3 orbites complètes à 3 hauteurs (bas ~30°, moyenne, haute en plongée), puis quelques plans
  rapprochés des détails importants.
* Scène B : se déplacer en « couronne » le long des murs en regardant vers le centre **et** vers les murs ;
  jamais de rotation pure sur place (pas de parallaxe → SfM impossible).
* **Recouvrement 70–80 %** entre images consécutives ; 150 à 300 images suffisent pour une pièce.
* Couvrir aussi le sol et le plafond si on veut les voir ; ce qui n'est pas vu ne sera pas reconstruit
  (ou le sera par des floaters).

## 2.3 Pré-traitement des images

Avec une vidéo, on extrait les images nettes avec `scripts/extract_frames.py` :

```bash
python3 scripts/extract_frames.py capture.mp4 data/sceneA/images --fps 3 --max-side 1920
```

Algorithme : fenêtres de $W = \text{fps}_\text{vidéo} / \text{fps}_\text{cible}$ images ; dans chaque
fenêtre on garde l'image maximisant la **variance du Laplacien** $\operatorname{Var}(\nabla^2 I)$ (mesure
de netteté : le flou supprime les hautes fréquences), puis on rejette les fenêtres dont la meilleure image
est sous 30 % de la netteté médiane. Résolution plafonnée à 1920 px : au-delà, le gain de détail est
faible et l'entraînement devient lent / demande plus de VRAM.

## 2.4 Outils de génération

| Outil | Où tourne le calcul | Plateforme | Points forts | Limites |
|---|---|---|---|---|
| **PostShot** (Jawset) | local (GPU NVIDIA) | Windows | interface simple, profils de qualité, contrôle du nombre max de splats, export PLY | GPU NVIDIA requis, licence gratuite limitée |
| **Polycam** | cloud | iOS, Android, web | très simple, export PLY | peu de contrôle sur l'entraînement, quotas |
| **Luma AI** | cloud | iOS, web | historique du domaine | l'entreprise s'est réorientée vers la vidéo générative : **vérifier la disponibilité** de la capture 3D |
| **Scaniverse** (Niantic) | sur le téléphone | iOS, Android | gratuit, calcul local, export PLY/SPZ | qualité moyenne sur grandes scènes |
| **Nerfstudio – splatfacto / gsplat** | local (CUDA) | Linux, Windows | open source, toutes les options (MCMC, compression, export cameras) | installation plus technique |
| **Brush** | local (WebGPU) | Windows, Linux, **macOS** | open source, fonctionne sur Apple Silicon | plus jeune |
| **OpenSplat** | local (CUDA / Metal / CPU) | multi, dont **macOS** | open source, entrée COLMAP | plus lent |

**Recommandation pour le projet** : PostShot si un PC NVIDIA ≥ 8 Go est disponible (c'est l'outil cité
dans le sujet), sinon Brush/OpenSplat sur Mac M1–M3 ; Polycam en plan B cloud. Si possible, entraîner aussi
la scène avec **gsplat/Nerfstudio** : on obtient les **poses caméras** (`cameras.json` / COLMAP) qui
permettent l'élagage « views » (§3.3) et la mesure de qualité contre les vraies photos (§4.4).

### Réglages de génération à consigner (pour la reproductibilité)
* nombre d'images, résolution, outil + version, profil (ex. PostShot « Splat3 » ou « Splat MCMC »),
  nombre d'itérations, **nombre max de gaussiennes**, temps d'entraînement, GPU ;
* garder une **vue de test** (1 image sur 8 non utilisée à l'entraînement) quand l'outil le permet.

### Pipeline open source (si l'outil ne fait pas le SfM)

```text
images/ ──COLMAP──► sparse/0 (cameras, images, points3D)
   feature_extractor (SIFT) → exhaustive_matcher (ou sequential_matcher pour la vidéo)
   → mapper (SfM incrémental + bundle adjustment) → image_undistorter (modèle PINHOLE)
sparse/0 ──3DGS / gsplat / Brush──► point_cloud.ply  (+ cameras.json)
```

## 2.5 Import dans le portail (détection automatique du format)

L'onglet **Modèles** accepte tout ce qui sort d'une capture. Le type est détecté d'après le **contenu**
du fichier (`scripts/formats.py`), pas d'après son extension :

| Détecté | Comment | Rangé dans | Étape suivante |
|---|---|---|---|
| Modèle 3DGS PLY | propriétés `opacity`, `scale_*`, `rot_*`, `f_dc_*` | `data/` | Analyser → Optimiser |
| PLY compressé PlayCanvas, SOG, SPZ, ksplat | élément `chunk`, archive SOG, en-tête gzip `NGSP` | `data/` | Convertir en PLY (splat-transform) |
| .splat, GSQ | taille multiple de 32 / signature `GSQ1` | `data/` | Optimiser |
| Vidéo (MP4, MOV, AVI, MKV, WebM) | boîte `ftyp`, EBML, RIFF ; durée et résolution lues par OpenCV | `data/captures/<nom>/` | Extraire les images |
| Photos (JPEG, PNG, HEIC, TIFF, WebP) ou ZIP de photos | signatures d'image | `data/captures/<groupe>/images/` | Générer le modèle |
| Nuage de points, maillage | PLY sans attributs de gaussienne / avec `face` | refusé à l'optimisation | — |

**Vérifier la capture avant d'entraîner** (`scripts/check_capture.py`, bouton « Vérifier la capture ») :
nombre d'images, netteté, variations d'exposition, focale (EXIF) et surtout **recouvrement**. Le script
apparie des points ORB entre paires d'images et les filtre par RANSAC sur la matrice fondamentale. Deux
vues sont « liées » au-delà de 50 correspondances fiables, et le graphe des liens doit former un seul
groupe dense. Le verdict (exploitable / limite / insuffisante) et les actions à mener s'affichent sur la
capture.

Premier cas réel, salle TAI A009 : 6 photos grand-angle de 4096×3072 px, nettes, toutes reliées en un
groupe (7 paires liées sur 15). Verdict « insuffisante » : 6 vues, c'est 20 à 50 fois moins que ce
qu'exige le 3DGS. Les EXIF avaient été supprimés lors du transfert, donc la focale est inconnue.

Deuxième cas réel, salle A014 : 165 photos (Nothing Phone 2a, 14 mm équivalent, 4080×3072 px).
L'échantillonnage des paires (2 836 sur 13 530) donnait 6 groupes. La seconde passe teste toutes les
paires entre groupes différents (6 668 de plus) : il reste **un groupe principal de 152 photos (92 %)**,
plus un groupe de 10 (angle de l'armoire, pris avec de grands écarts), une paire et une photo isolée.
Verdict « limite », capture utilisable. Le dossier `postshot_input/` écarte les 5 photos floues et la
photo isolée : 159 images. Leçon : ne jamais conclure à une coupure sur un échantillon de paires.

**Vidéo → modèle** : « Extraire les images » lance `extract_frames.py` (meilleure netteté par fenêtre,
cf. 2.3). « Générer le modèle » lance `train_3dgs.py`, qui utilise l'outil d'entraînement installé :
nerfstudio (splatfacto), ou COLMAP + OpenSplat. Sans outil local, le script indique la marche à suivre :
PostShot avec la vidéo ou les images, Polycam avec l'« Archive ZIP des photos », ou Brush. On importe
ensuite le .ply obtenu.

⚠️ `train_3dgs.py` n'a pas pu être testé dans l'environnement de développement : aucun outil
d'entraînement n'y est installé (machine de développement : GTX 1650 Ti, 4 Go de VRAM, sous les 8 Go
recommandés par le sujet).

## 2.6 Contrôle qualité du modèle généré

1. `python3 scripts/analyze.py scene.ply --plot data/sceneA/histos.png` : nombre de gaussiennes, part des
   SH, distributions d'opacité / taille / distance, nombre de candidats au nettoyage ;
2. inspection visuelle dans SuperSplat ou dans `viewer/` (floaters, trous, halo) ;
3. consigner ces chiffres : ce sont les valeurs « avant » du rapport.
