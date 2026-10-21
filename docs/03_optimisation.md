# 3. Méthodes et algorithmes d'optimisation

> Livrable « Optimisation ». Pour chaque méthode : **principe**, **formulation**, **algorithme**,
> **complexité**, **paramètres**, **risques visuels**, et le **script** qui l'implémente dans `scripts/`.
> Notations du chapitre 1 : $N$ gaussiennes, centre $\mu_j$, échelles $s_j$, opacité
> $\sigma_j = \operatorname{sigmoid}(o_j)$, SH $k_j$.

## 3.1 Vue d'ensemble

On distingue cinq familles complémentaires, appliquées dans cet ordre :

```text
  modèle brut ──► [A] Nettoyage ──► [B] Élagage ──► [C] Réduction SH ──► [D] Quantification ──► [E] Codage entropique ──► fichier web
                 retire le faux    retire le      réduit les attributs   réduit les bits        exploite la redondance
                 (floaters, halo)  redondant      par gaussienne         par attribut           entre gaussiennes
                 ↓N                ↓N             ↓ octets/gaussienne    ↓ octets/gaussienne    ↓ octets totaux
```

* **A et B** diminuent $N$ : gain sur la taille **et** sur la fluidité (moins de tri, moins de surdessin).
* **C, D, E** diminuent les octets par gaussienne : gain sur la taille et le temps de téléchargement, mais
  pas (ou peu) sur le FPS, car le visualiseur décompresse tout en mémoire.
* Les gains se **multiplient** : ex. 0,5 (élagage) × 1/13 (quantification + VQ) ≈ ×26 de compression.

### État de l'art (repères bibliographiques)

| Méthode | Idée principale | Ré-entraînement ? |
|---|---|---|
| LightGaussian (Fan et al., NeurIPS 2024) | élagage par « importance globale », distillation des SH, quantification vectorielle | oui (fine-tuning court) |
| Compact 3DGS (Lee et al., CVPR 2024) | masque appris pour supprimer des gaussiennes, couleur par grille de hachage, VQ résiduelle | oui |
| C3DGS (Niedermayr et al., CVPR 2024) | VQ guidée par la sensibilité des paramètres, tri de Morton, compression entropique | fine-tuning |
| EAGLES (Girish et al., ECCV 2024) | attributs quantifiés via un petit décodeur | oui |
| Reduced3DGS (Papantonakis et al., 2024) | élagage des redondances + degré SH adaptatif par gaussienne + codebook | oui |
| Self-Organizing Gaussians (Morgenstern et al., ECCV 2024) | tri des gaussiennes sur une grille 2D lisse, compression des attributs comme des images | non (post-traitement) |
| Scaffold-GS / HAC (Lu et al. ; Chen et al. 2024) | gaussiennes générées par des « ancres » + réseau, codage entropique contextuel | oui (autre représentation) |
| Formats industriels | PlayCanvas *compressed.ply* et *SOG*, Niantic *SPZ*, *.ksplat* | non |

Les résultats publiés font état de compressions de l'ordre de ×10 à ×50 (et plus pour les approches à
ancres), avec une perte de PSNR faible quand un fine-tuning est fait. **Ce projet se concentre sur le
post-traitement sans ré-entraînement** (outils accessibles, pas besoin des images d'origine), et quantifie
ce qu'on perd en ne ré-entraînant pas.

---

## 3.2 [A] Nettoyage — `scripts/clean.py`

Les filtres sont des **masques booléens** appliqués en cascade ; chaque étape journalise le nombre de
gaussiennes retirées (`--report clean.json`). L'ordre est choisi pour que les filtres bon marché et sûrs
passent en premier et que les filtres statistiques (A5, A6) travaillent sur des données déjà saines.

### A1 — Valeurs invalides
Retirer toute gaussienne dont un attribut est NaN/Inf ou dont le quaternion est nul. Coût $O(N)$.
Indispensable : un seul NaN fausse les médianes, quantiles et bornes de quantification.

### A2 — Opacité négligeable
$$ \text{garder } j \iff \sigma_j \ge \tau_\alpha $$
Une gaussienne avec $\sigma_j < 1/255$ ne peut pas modifier un pixel 8 bits de plus d'une unité, même
seule : sa suppression est **sans perte visible** (preset `light`). Avec $\tau_\alpha = 0{,}02$ (preset
`aggressive`), on retire aussi des gaussiennes faibles mais nombreuses qui, empilées, contribuent : à
vérifier visuellement (voiles, cheveux, feuillages).
Le visualiseur `gaussian-splats-3d` applique lui-même un seuil (`splatAlphaRemovalThreshold`, défaut 1/255).

### A3 — Échelle aberrante
$$ s^{max}_j = \max_i e^{\text{scale}_{j,i}},\qquad \text{garder } j \iff s^{max}_j \le k \cdot \operatorname{médiane}(s^{max}) $$
Cible les gaussiennes géantes (floaters « nuages », halo de fond) qui coûtent cher en surdessin.
Option d'anisotropie $s^{max}/s^{min} \le R$ contre les « aiguilles » ; à utiliser avec prudence car les
gaussiennes plates ($s^{min} \approx 0$) sont normales sur les surfaces.
Paramètre : $k$ = 30 (`medium`), 15 (`aggressive`). Risque : ciel ou murs uniformes représentés par de
grandes gaussiennes légitimes → préférer un recadrage (A4) pour le fond.

### A3b — Floaters : peu opaques **et** gros
$$ \text{retirer } j \iff \sigma_j < a \;\wedge\; s^{max}_j > m \cdot \operatorname{médiane}(s^{max}) $$
Ni l'opacité seule (les petites gaussiennes transparentes des bords sont utiles) ni la taille seule (les
grandes gaussiennes opaques des murs aussi) ne caractérisent un floater ; leur conjonction, oui.
Défaut $a = 0{,}2$, $m = 5$ (`medium`). Sur la scène test : 6 986 des 7 000 floaters injectés retirés,
aucune gaussienne du contenu touchée — alors qu'ils passaient à travers A2 et A3 pris séparément.

### A4 — Recadrage spatial
* **Manuel** : boîte `--box xmin ymin zmin xmax ymax zmax` ou sphère `--sphere cx cy cz r` (coordonnées lues
  dans SuperSplat ou le visualiseur).
* **Automatique robuste** :
$$ c = \operatorname{médiane}(\mu),\quad d_j = \lVert \mu_j - c\rVert,\quad
\text{garder } j \iff d_j \le f \cdot Q_q(d) $$
  (médiane et quantile $Q_q$ sont insensibles aux points extrêmes, contrairement à la moyenne et
  l'écart-type). Défaut $q = 0{,}99$, $f = 2$. Coût $O(N)$.
Risque : supprime l'arrière-plan lointain (ciel, horizon) qui peut faire partie de l'expérience.

### A5 — Statistical Outlier Removal (SOR)
Méthode classique des nuages de points (PCL, Rusu et al. 2008) :
$$ \bar d_j = \frac1k \sum_{i \in \mathcal{N}_k(j)} \lVert \mu_j - \mu_i \rVert,\qquad
\text{garder } j \iff \bar d_j \le \operatorname{moy}(\bar d) + n_\sigma \cdot \operatorname{écart-type}(\bar d) $$
Algorithme : construire un **k-d tree** ($O(N\log N)$), requête des $k$ plus proches voisins
($O(N k \log N)$), seuillage. Paramètres : $k = 16$, $n_\sigma = 2$. Nécessite `scipy`.
Retire les gaussiennes isolées dans le vide (floaters ponctuels).

### A6 — Densité locale sur grille de voxels (sans dépendance)
Alternative $O(N\log N)$ en numpy pur, plus robuste aux très gros nuages :
1. taille de voxel automatique $v = f \cdot \left( V_{90\%} / N \right)^{1/3}$ où $V_{90\%}$ est le volume
   de la boîte englobante des quantiles 5–95 % ;
2. indices de voxel $(i,j,k) = \lfloor (\mu - \mu_{min}) / v \rfloor$, linéarisés en une clé entière 64 bits ;
3. `np.unique` → nombre de points par voxel occupé ;
4. pour chacun des 27 décalages $(\pm1, 0)^3$, recherche dichotomique de la clé voisine
   (`np.searchsorted`) et cumul des effectifs ;
5. garder $j$ si son 27-voisinage contient au moins $m$ autres points ($m$ = 3 à 5).

### A7 — Édition manuelle dans SuperSplat
Les filtres automatiques ne remplacent pas un passage manuel pour les floaters « accrochés » à la scène :

1. ouvrir le PLY dans **SuperSplat** (navigateur, superspl.at/editor) ;
2. outils de sélection : rectangle, pinceau, sphère, **sélection par plage d'opacité/taille** (panneau
   données) ; inverser la sélection pour isoler la zone utile ;
3. *Delete* sur les floaters, recadrage par boîte, vérification depuis plusieurs vues ;
4. exporter en PLY (pour continuer la chaîne de scripts) ou en *compressed.ply* / SOG (diffusion).

Bonne pratique : **scripts d'abord** (reproductibles, chiffrés), **SuperSplat ensuite** pour les
retouches, et noter le nombre de gaussiennes supprimées à la main.

---

## 3.3 [B] Élagage par importance — `scripts/prune.py`

Après nettoyage, il reste des gaussiennes *valides mais redondantes* (sur-densification). On leur attribue
un **score d'importance** $I_j$ et on garde les $\rho N$ meilleures (`--keep-ratio ρ`), sélection en $O(N)$
par `argpartition`.

### B1 — Score proxy (sans caméras)
$$ I_j = \sigma_j \cdot \min\!\left(\frac{V_j}{V_{90}}, 1\right)^{\beta}, \qquad V_j = s_{j,1}\, s_{j,2}\, s_{j,3} $$
Une gaussienne compte d'autant plus qu'elle est opaque et volumineuse ; $V_{90}$ (quantile 90 %) normalise
et plafonne le volume pour qu'une gaussienne géante ne soit pas favorisée ; $\beta = 0{,}1$ rend le volume
secondaire par rapport à l'opacité (même choix que LightGaussian). Coût $O(N)$.
Limite : ignore la position par rapport aux caméras (une gaussienne cachée derrière un mur garde un bon score).

### B2 — Score « views » (importance globale, inspiré de LightGaussian)
LightGaussian définit l'importance comme la somme, sur tous les pixels de toutes les vues d'entraînement, des
contributions de la gaussienne :
$$ GS_j = \sum_{\text{vues}} \sum_{\text{pixels } r} \mathbb{1}\big(G_j \text{ touche } r\big)\cdot \sigma_j \cdot \gamma(\Sigma_j) $$
Sans rasteriseur, on l'approche par :
$$ I_j = \sum_{c \in \text{caméras}} \sigma_j \cdot A_j(c) \cdot \text{vis}_j(c),
\qquad A_j(c) = \min\!\left(\pi \frac{3 s_a f_x}{z}\cdot\frac{3 s_b f_y}{z},\; W H\right) $$
* $z$ = profondeur dans la caméra, $s_a \ge s_b$ les deux plus grandes échelles : $A_j$ est l'aire (en
  pixels) de l'ellipse à $3\sigma$ vue de face — une borne haute du nombre de pixels touchés ;
* $\text{vis}_j(c)$ : la gaussienne est dans le champ (avec marge de son rayon), devant la caméra, et —
  option `--occlusion` — **non occultée** : on construit un z-buffer basse résolution (cellules 8×8 px)
  rempli par la profondeur minimale des gaussiennes opaques ($\sigma > 0{,}5$) via `np.minimum.at`, et on
  ne compte une gaussienne que si $z \le z_\text{buffer}(1 + 5\%)$.
* Caméras : poses d'acquisition COLMAP (`cameras.txt` + `images.txt`) ou `cameras.json` (3DGS/gsplat), ou
  à défaut `--orbit N` caméras virtuelles autour du centre de la scène.

Coût : $O(N \cdot C)$ vectorisé (C caméras) : ≈ 3 s pour 180 k gaussiennes et 32 caméras.

**Validation** (scène synthétique contenant 20 % de gaussiennes cachées à l'intérieur des objets, cf. 4.4) :
en gardant 80 % des gaussiennes, le score views **avec occultation** élimine 72 % des gaussiennes cachées
et conserve 92–100 % du contenu visible ; le proxy et le score views sans occultation gardent 93 % des
cachées et sacrifient le sol visible. L'occultation est donc l'ingrédient décisif.
Biais connu : le poids $1/z^2$ favorise les zones proches des caméras ; si les caméras de score diffèrent
des points de vue réels d'utilisation, des zones lointaines peuvent être vidées (observé sur une scène sans
redondance). Utiliser de préférence les **poses réelles** d'acquisition.

### B3 — Ré-entraînement court (hors scripts, optionnel)
Après un élagage fort (ρ < 0,4), un fine-tuning de quelques milliers d'itérations avec les images
d'origine (gsplat, Nerfstudio) permet aux gaussiennes restantes de combler les trous. C'est ce qui permet à
LightGaussian d'atteindre ~66 % d'élagage sans perte notable. À tester si le temps le permet : c'est la
différence principale entre « post-traitement » et « compression apprise ».

**Risques visuels de l'élagage** : trous dans les surfaces peu texturées (sol, murs), perte des détails fins
(feuillages, câbles), « peau » plus transparente. Le taux supportable dépend entièrement de la redondance du
modèle : sur une scène test sans redondance, élaguer 50 % donne déjà des trous (PSNR ≈ 22 dB). Il faut donc
tracer, **pour chaque scène**, la courbe PSNR en fonction de ρ et choisir le coude.

---

## 3.4 [C] Réduction des harmoniques sphériques — `scripts/sh_reduce.py`

### C1 — Troncature de degré
On ne garde que les ordres $l \le L'$ : de 236 à 152 (L'=2), 92 (L'=1) ou 56 octets (L'=0).
Perte : les reflets et la brillance (couleur figée). Sur des scènes mates, la différence est souvent
imperceptible ; sur des objets brillants (carrosserie, métal, sol ciré) elle est nette.
Le format `.splat` impose $L' = 0$ ; `gaussian-splats-3d` rend au plus le degré 2.

### C2 — SH adaptatifs (par gaussienne)
Énergie relative de la partie dépendante de la vue :
$$ e_j = \frac{\lVert k_{j,l\ge1}\rVert_2}{\lVert k_{j,0}\rVert_2} $$
Si $e_j < \tau$ (ex. 0,05), la gaussienne est quasi diffuse : on met ses SH d'ordre ≥ 1 à zéro. Dans un
PLY la taille ne change pas, mais ces zéros sont gratuits après quantification vectorielle (index 0 réservé)
ou codage entropique. Idée proche de Reduced3DGS (degré choisi par gaussienne).

### C3 — Distillation (non implémentée, ré-entraînement)
LightGaussian ré-entraîne un modèle de degré inférieur en lui faisant imiter le modèle de degré 3 sur des
vues virtuelles supplémentaires (pseudo-vues) : on garde une partie des effets de vue avec moins de
coefficients.

---

## 3.5 [D+E] Quantification et codage entropique — `scripts/gsq.py`

### D1 — Quantification scalaire uniforme
Pour une valeur $x \in [a, b]$ codée sur $B$ bits :
$$ q = \operatorname{round}\!\left(\frac{x - a}{b - a}\,(2^B - 1)\right), \qquad \hat x = a + \frac{q}{2^B - 1}(b-a) $$
Erreur maximale $\Delta/2$ et erreur quadratique moyenne $\Delta/\sqrt{12}$ avec $\Delta = (b-a)/(2^B-1)$.
Le choix de la plage $[a,b]$ est crucial : on utilise des **plages locales par bloc** (positions, échelles)
ou des **quantiles robustes** (couleur : 0,05 %–99,95 %) pour qu'un point extrême ne dilate pas $\Delta$.

### D2 — Tri de Morton et blocs
Code de Morton (courbe en Z) : on quantifie chaque coordonnée sur 21 bits et on **entrelace** leurs bits
$$ m = \dots z_1 y_1 x_1\, z_0 y_0 x_0 $$
(opération « part1by2 » par masques et décalages, $O(N)$, puis tri $O(N \log N)$). Deux gaussiennes
proches dans l'espace ont des codes proches : après tri, chaque **bloc de 256 gaussiennes consécutives**
occupe un petit volume. On stocke la boîte min/max de chaque bloc (24 octets/bloc ≈ 0,1 octet/gaussienne)
et les positions **relatives au bloc** sur 16 bits (ou 11-10-11 bits dans un entier 32 bits).
Précision obtenue sur la scène test : erreur de position RMS = $5\cdot10^{-7}$ × la taille de la scène.
Le tri améliore aussi le codage entropique (attributs voisins similaires). C'est le principe du
*compressed.ply* de PlayCanvas/SuperSplat.

### D3 — Rotation : « smallest three »
Un quaternion unitaire $q$ et $-q$ représentent la même rotation, et $\sum q_i^2 = 1$. On :
1. normalise $q$, repère l'indice $i^\*$ de la plus grande composante en valeur absolue, rend
   $q_{i^\*} > 0$ (multiplication par −1 si besoin) ;
2. stocke $i^\*$ sur 2 bits et les 3 autres composantes, qui sont dans $[-1/\sqrt2, 1/\sqrt2]$, sur
   10 bits chacune → **32 bits** au lieu de 128 ;
3. au décodage : $q_{i^\*} = \sqrt{1 - \sum_{i\ne i^\*} q_i^2}$.
Erreur mesurée : 0,11° en moyenne.

### D4 — Échelles, couleur, opacité
* log-échelles : 8 bits par axe, plage min/max **par bloc** ;
* couleur DC : 8 bits par canal (plage globale robuste) ; erreur RMS mesurée 0,22/255 ;
* opacité : 8 bits sur $\sigma$ (et non sur le logit, pour que l'erreur soit uniforme en contribution
  visuelle) ; au décodage, $\operatorname{logit}$ borné à $\pm \operatorname{logit}(0{,}5/255)$.

### D5 — SH : quantification scalaire 8 bits ou **quantification vectorielle (VQ)**
* *8 bits* : chaque coefficient sur un octet, plage symétrique $[-r, r]$, $r = Q_{99,9\%}(|k|)$ :
  45 octets/gaussienne en degré 3.
* *VQ* : les 45 coefficients d'une gaussienne forment un vecteur $v_j \in \mathbb{R}^{45}$. On apprend un
  **dictionnaire** $\{c_1..c_K\}$ par **k-means** et on ne stocke que l'index du centre le plus proche
  (16 bits pour $K \le 65\,536$) + le dictionnaire en float16 :

```text
k-means de Lloyd (scripts/gsq.py:kmeans)
  S ← sous-échantillon de ≤ 200 000 vecteurs
  C ← K vecteurs tirés au hasard dans S
  répéter T fois (T = 10) :
      affectation : l_j = argmin_k ||v_j − c_k||²      (calcul matriciel : ||v||² − 2 v·c + ||c||²)
      mise à jour : c_k = moyenne des v_j tels que l_j = k   (tri par label + np.add.reduceat)
      centres vides : réinitialisés sur un point au hasard
  affectation finale de tous les N vecteurs par lots
```
Complexité $O(T \cdot S \cdot K \cdot D)$ pour l'apprentissage, $O(N K D)$ pour l'affectation.
Avec l'option `--sh-zero τ` (SH adaptatifs, C2), l'entrée 0 du dictionnaire est le vecteur nul.
Gain : 180 octets (float32) → 2 octets d'index + un dictionnaire fixe de 360 Ko (K = 4096 × 45 × 2 octets),
amorti sur toutes les gaussiennes (négligeable au-delà du million ; sur une petite scène, réduire K).
Amélioration possible (C3DGS) : k-means **pondéré par l'importance** $I_j$ pour que le dictionnaire
représente bien les gaussiennes qui comptent.

### E — Codage entropique
1. **Byte shuffle** : pour un tableau d'entiers 16/32 bits, on regroupe tous les octets de poids fort, puis
   tous ceux de poids faible (comme Blosc) : les octets de poids fort, très répétitifs, se compressent mieux.
2. **LZMA** (défaut, ou zlib) sur la concaténation des sections.
L'en-tête JSON décrit chaque section (nom, type, forme) : le format est auto-descriptif et versionné.

### Format GSQ v1 (récapitulatif, avant codage entropique)

| Section | Contenu | Octets / gaussienne |
|---|---|---|
| `pos` | positions relatives au bloc, uint16 ×3 (ou 11-10-11 dans uint32) | 6 (ou 4) |
| `pos_bounds` | min/max par bloc de 256, float32 ×6 | 0,09 |
| `scale` | log-échelles relatives au bloc, uint8 ×3 | 3 |
| `scale_bounds` | min/max par bloc, float32 ×6 | 0,09 |
| `rot` | smallest-three 2+10+10+10 bits | 4 |
| `dc` | couleur, uint8 ×3 | 3 |
| `alpha` | opacité, uint8 | 1 |
| `sh_index` + `sh_codebook` | VQ : uint16 + dictionnaire float16 | 2 + K·45·2/N |
| *ou* `sh` | 8 bits : uint8 × 45 | 45 |
| **Total (VQ)** | | **≈ 19 avant LZMA, 14,3 après** (scène test) |

Le décodeur (`gsq.py decode`) reconstruit un PLY standard : c'est ce fichier que l'on charge dans le
visualiseur pour **mesurer la perte visuelle**, tandis que la **taille** retenue est celle du `.gsq`.
(Intégrer un décodeur GSQ directement en JavaScript est une extension possible, cf. chap. 6.)

---

## 3.6 Formats de diffusion existants

| Format | Octets / gaussienne (ordre de grandeur) | SH | Remarques |
|---|---|---|---|
| PLY Inria | 248 (236 sans normales) | 0–3 | référence, non compressé |
| `.splat` (antimatter15) | 32 | non | float32 position/échelle, couleur RGBA 8 bits, quaternion 4×8 bits ; trié par importance |
| `.ksplat` (gaussian-splats-3d) | ~ 1/2 à 1/4 du PLY selon niveau 0/1/2 | 0–2 | niveaux de compression en demi-précision / 8 bits, organisation en blocs spatiaux |
| *compressed.ply* (PlayCanvas/SuperSplat) | ~ 16 + SH 8 bits | 0–3 | blocs de 256 triés Morton, positions 11-10-11, rotation 2-10-10-10, échelles 11-10-11, couleur+opacité 8 bits |
| SOG (PlayCanvas) | encore plus faible | 0–3 | attributs rangés en images WebP + VQ des SH (dans la lignée de Self-Organizing Gaussians) |
| SPZ (Niantic) | ~ 1/10 du PLY | 0–3 | quantification + gzip, lu par plusieurs visualiseurs |
| GSQ (ce projet) | 14 (VQ, LZMA) | 0–3 | expérimental, transparent, pour l'étude |

Conversions pratiques : SuperSplat (export), `npx @playcanvas/splat-transform` (PLY ↔ compressed.ply / SOG
selon la version), l'outil de conversion de `gaussian-splats-3d` pour le `.ksplat`, `gsply.write_splat`
pour le `.splat`. **Vérifier les options exactes dans la documentation de la version installée.**

---

## 3.7 Récapitulatif : effet attendu de chaque méthode

| Méthode | ↓ Taille | ↑ FPS | ↓ Chargement | Risque qualité | Paramètre clé |
|---|---|---|---|---|---|
| A1–A2 invalides / α faible | faible | faible à moyen | faible | nul | $\tau_\alpha$ = 1/255 |
| A3–A6 aberrants / floaters | faible | **fort** (surdessin) | faible | faible (sauf fond légitime) | k, q, n_σ |
| B élagage | proportionnel à ρ | **fort** | proportionnel | moyen à fort si ρ < 0,4 | ρ |
| C1 degré SH | ×1,6 (L=2) à ×4,2 (L=0) | léger | fort | reflets | L' |
| D quantification + VQ | ×10 à ×17 | nul* | **fort** (téléchargement) | très faible | K, bits |
| E entropie | ×1,2 à ×1,5 en plus | nul | moyen | nul (sans perte) | — |

\* le visualiseur décompresse en mémoire ; certains (PlayCanvas, SOG) gardent les données compressées en
mémoire GPU et gagnent aussi en bande passante.
