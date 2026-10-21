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

## 2.5 Contrôle qualité du modèle généré

1. `python3 scripts/analyze.py scene.ply --plot data/sceneA/histos.png` : nombre de gaussiennes, part des
   SH, distributions d'opacité / taille / distance, nombre de candidats au nettoyage ;
2. inspection visuelle dans SuperSplat ou dans `viewer/` (floaters, trous, halo) ;
3. consigner ces chiffres : ce sont les valeurs « avant » du rapport.
