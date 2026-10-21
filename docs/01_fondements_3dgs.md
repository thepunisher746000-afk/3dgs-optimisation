# 1. Fondements du 3D Gaussian Splatting

> Objectif de ce chapitre : comprendre **ce que contient** un fichier 3DGS et **pourquoi il est lourd et
> coûteux à afficher**. Chaque méthode d'optimisation du chapitre 3 agit sur l'un des termes définis ici.

Référence principale : B. Kerbl, G. Kopanas, T. Leimkühler, G. Drettakis, *3D Gaussian Splatting for
Real-Time Radiance Field Rendering*, ACM TOG (SIGGRAPH) 2023.

---

## 1.1 Représentation : un nuage de gaussiennes anisotropes

Une scène est un ensemble de $N$ primitives (typiquement $N$ = 0,5 à 6 millions). Chaque gaussienne $j$ est
une « goutte » 3D floue définie par :

| Paramètre | Symbole | Nb de flottants | Stockage dans le PLY |
|---|---|---|---|
| Centre | $\mu_j \in \mathbb{R}^3$ | 3 | `x y z` |
| Rotation | quaternion $q_j$ | 4 | `rot_0..3` (w,x,y,z), non normalisé |
| Échelles | $s_j \in \mathbb{R}^3$ | 3 | `scale_0..2` = $\log s$ |
| Opacité | $\sigma_j \in [0,1]$ | 1 | `opacity` = $\operatorname{logit}(\sigma)$ |
| Couleur (SH ordre 0) | $k_{j,0}$ | 3 | `f_dc_0..2` |
| Couleur (SH ordres 1..3) | $k_{j,l\ge1}$ | 45 | `f_rest_0..44` |
| *(normales, inutilisées)* | — | 3 | `nx ny nz` (toujours 0) |

Total : **59 flottants utiles + 3 normales = 62 × 4 octets = 248 octets par gaussienne**.
Un modèle de 3 millions de gaussiennes pèse donc ≈ **744 Mo** : c'est le problème central du projet.

Les paramétrisations (log, logit, quaternion) existent pour l'optimisation par gradient : elles garantissent
une échelle positive, une opacité dans $[0,1]$ et une rotation valide quelles que soient les valeurs.

### Densité de la gaussienne

$$ G_j(x) = \exp\!\left(-\tfrac12 (x-\mu_j)^\top \Sigma_j^{-1} (x-\mu_j)\right),
\qquad \Sigma_j = R_j S_j S_j^\top R_j^\top $$

avec $R_j$ la matrice de rotation issue de $q_j$ et $S_j = \operatorname{diag}(s_j)$. Cette factorisation
garantit que $\Sigma_j$ reste symétrique définie positive. Une gaussienne peut être une sphère, un disque
plat ($s_3 \approx 0$, typique des surfaces) ou une aiguille.

### Couleur dépendante du point de vue : harmoniques sphériques (SH)

La couleur vue depuis la direction $d$ est

$$ c_j(d) = 0{,}5 + \sum_{l=0}^{L} \sum_{m=-l}^{l} k_{j,l}^{m}\, Y_l^m(d), $$

où $Y_l^m$ sont les harmoniques sphériques réelles. En degré $L = 3$ il y a $(L+1)^2 = 16$ coefficients par
canal RGB, soit 48 flottants. L'ordre 0 ($Y_0^0 = 0{,}28209$) donne la couleur « diffuse » :
$\text{rgb} = 0{,}5 + 0{,}28209 \cdot f_{dc}$. Les ordres 1 à 3 (45 flottants) ne servent qu'aux
**effets dépendant de la vue** (reflets, brillance) mais représentent **76 % des paramètres**.

| Degré SH | coef. « rest » / canal | flottants / gaussienne (sans normales) | octets |
|---|---|---|---|
| 0 | 0 | 14 | 56 |
| 1 | 3 | 23 | 92 |
| 2 | 8 | 38 | 152 |
| 3 | 15 | 59 | 236 |

## 1.2 Rendu : rasterisation différentiable par tuiles

1. **Projection (EWA splatting, Zwicker et al. 2001)** : la covariance 3D est projetée en 2D par
   $\Sigma'_j = J W \Sigma_j W^\top J^\top$, où $W$ est la transformation monde→caméra et $J$ le jacobien
   de la projection perspective (approximation affine locale). On garde le bloc 2×2.
2. **Culling** : on écarte les gaussiennes hors du frustum ; le rayon écran vaut $3\sqrt{\lambda_{max}(\Sigma'_j)}$.
3. **Tri** : l'image est découpée en tuiles 16×16 ; chaque gaussienne est dupliquée dans les tuiles
   qu'elle touche avec une clé (tuile | profondeur), puis un *radix sort* GPU global ordonne tout.
4. **Composition alpha avant→arrière** pour chaque pixel :

$$ C = \sum_{i=1}^{n} c_i\, \alpha_i \prod_{k=1}^{i-1} (1-\alpha_k),
\qquad \alpha_i = \sigma_i \exp\!\left(-\tfrac12 \delta_i^\top \Sigma_i'^{-1} \delta_i\right) $$

   avec $\delta_i$ l'écart pixel–centre projeté. On s'arrête quand la transmittance $\prod(1-\alpha_k) < 10^{-4}$.

### Ce qui coûte à l'affichage

* **Nombre de gaussiennes $N$** : projection + tri en $O(N \log N)$ (ou $O(N)$ en tri par comptage) à
  chaque changement de point de vue.
* **Surdessin (overdraw)** : chaque pixel compose toutes les gaussiennes qui le recouvrent. Une grosse
  gaussienne transparente proche de la caméra coûte des milliers de pixels pour une contribution quasi
  nulle. C'est pourquoi les « floaters » et le halo de fond dégradent fortement la fluidité
  (mesuré dans ce projet : **0,7 FPS → 30 FPS** sur la scène synthétique en retirant seulement ~2 % de
  gaussiennes géantes du halo, cf. chap. 4).
* **Bande passante mémoire** : lecture des attributs (SH surtout) pour chaque fragment.

### Spécificités du web (WebGL)

WebGL 2 n'a pas de *compute shaders* : les visualiseurs web (antimatter15/splat,
`@mkkellogg/gaussian-splats-3d`, PlayCanvas/SuperSplat, Spark) :
* trient les gaussiennes **sur CPU dans un Web Worker** (tri par comptage sur des profondeurs entières
  16 bits, parfois en WebAssembly), de façon asynchrone : l'image peut être affichée avec un tri
  légèrement en retard ;
* stockent les attributs dans des **textures** (souvent en demi-précision) lues par un *vertex shader* qui
  dessine un quad par gaussienne (rendu instancié) ;
* limitent souvent le degré SH (0 à 2 pour `gaussian-splats-3d`).

Le **temps de chargement** = téléchargement (taille du fichier) + décodage/parsing en JavaScript +
envoi au GPU. Les deux premiers termes sont directement réduits par l'optimisation.

## 1.3 Entraînement (génération du modèle)

1. **Structure-from-Motion** (COLMAP) : estimation des poses caméras et d'un nuage de points épars.
2. **Initialisation** : une gaussienne par point SfM (échelle = distance moyenne aux 3 voisins).
3. **Optimisation** (≈ 30 000 itérations, Adam) d'une perte photométrique sur les images d'entraînement :
   $\mathcal{L} = (1-\lambda)\,\mathcal{L}_1 + \lambda\,\mathcal{L}_{\text{D-SSIM}}$, $\lambda = 0{,}2$.
4. **Contrôle adaptatif de densité** (toutes les 100 itérations jusqu'à 15 000) :
   * *clone* : petite gaussienne avec fort gradient de position (zone sous-reconstruite) → duplication ;
   * *split* : grande gaussienne à fort gradient → remplacée par 2 plus petites (échelle / 1,6) ;
   * *prune* : suppression si $\sigma < 0{,}005$ ou trop grande ;
   * *reset d'opacité* toutes les 3 000 itérations pour éliminer les gaussiennes inutiles.

Ce mécanisme **sur-densifie** volontairement (la qualité prime sur la compacité), d'où la redondance que
l'élagage (chap. 3) peut retirer. Il produit aussi les **floaters** : des gaussiennes placées dans le vide
pour expliquer des reflets, des zones mal couvertes ou des erreurs de pose, visibles uniquement depuis les
vues d'entraînement.

Variantes utiles : **3DGS-MCMC** (Kheradmand et al. 2024, nombre de gaussiennes fixé à l'avance — option
« MCMC » de PostShot), **Mini-Splatting**, **Taming 3DGS** (budget contrôlé), qui produisent directement des
modèles plus compacts.

## 1.4 Conséquences pour le projet

| Constat | Levier d'optimisation (chap. 3) |
|---|---|
| Beaucoup de gaussiennes invisibles/inutiles | nettoyage (§3.2), élagage par importance (§3.3) |
| 76 % des données = SH ordres ≥ 1 | réduction de degré SH, SH adaptatifs, quantification vectorielle (§3.4, §3.5) |
| Flottants 32 bits sur-précis | quantification 8–16 bits (§3.5) |
| Gaussiennes voisines aux attributs corrélés | tri de Morton + codage entropique (§3.5) |
| Coût de surdessin | suppression des grosses gaussiennes transparentes, seuil alpha du visualiseur |
