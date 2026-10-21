# 6. Plan de travail, livrables et suites

## 6.1 Planning indicatif (10 semaines, à adapter au calendrier du projet)

| Sem. | Tâche | Livrable | État |
|---|---|---|---|
| 1 | Bibliographie, prise en main de SuperSplat et d'un visualiseur, outillage Python | chap. 1, `scripts/` | ✅ v0.1 |
| 2 | Validation de la chaîne sur scène synthétique | chap. 3 & 4.4 | ✅ v0.1 |
| 3 | Capture scène A (objet/extérieur) + génération PostShot (ou Brush/Polycam) | `data/sceneA/`, fiche capture | ⏳ |
| 4 | Capture scène B (intérieur) + génération ; analyse des deux modèles | `analyze.py` sur A et B | ⏳ |
| 5 | Nettoyage : réglage des filtres, comparaison avec un nettoyage manuel SuperSplat | tableau nettoyage | ⏳ |
| 6 | Élagage : courbes qualité / ρ (proxy vs views, avec/sans occultation) | courbes PSNR–taille | ⏳ |
| 7 | SH + quantification : comparaison GSQ / compressed.ply / SOG / SPZ / ksplat | tableau formats | ⏳ |
| 8 | Campagne de mesures web sur 2 appareils (PC + mobile), réseau simulé | `results/*.json` | ⏳ |
| 9 | (option) fine-tuning après élagage avec gsplat ; mesure contre les photos | — | ⏳ |
| 10 | Guide de bonnes pratiques final, rapport, soutenance | chap. 5 v1.0 | ⏳ |

## 6.2 Questions à poser à l'encadrant

1. Scènes attendues : un lieu précis (labo, campus) ? une ou plusieurs ?
2. Appareil cible prioritaire : PC navigateur, mobile, casque (WebXR) ?
3. Le ré-entraînement (fine-tuning après élagage) est-il dans le périmètre ?
4. Faut-il un visualiseur « produit » (intégration finale) en plus du banc de mesure ?
5. Matériel disponible : PC NVIDIA du labo / licence PostShot ?

## 6.3 Risques

| Risque | Parade |
|---|---|
| Pas de GPU NVIDIA disponible | Brush / OpenSplat (Mac), Polycam (cloud) |
| Capture ratée (SfM échoue) | refaire avec plus de recouvrement ; vidéo + `extract_frames.py` |
| FPS plafonné à 60 partout | appareil plus faible, résolution 1080p, Chrome sans vsync |
| Outil cloud indisponible / payant | outils locaux open source |
| Formats et outils qui évoluent vite | noter les versions ; les scripts du projet n'en dépendent pas |

## 6.4 Extensions possibles

* Décodeur GSQ en JavaScript (Web Worker) pour charger directement le `.gsq` dans le visualiseur et
  mesurer le temps de décodage réel.
* k-means pondéré par l'importance (à la C3DGS) et dictionnaires séparés par degré SH.
* Degré SH choisi par gaussienne (C2 généralisé) plutôt que tout-ou-rien.
* Niveaux de détail : plusieurs fichiers (20 % / 50 % / 100 % des gaussiennes par importance) chargés
  progressivement.
* Élagage « views » avec un vrai rasteriseur (gsplat) pour compter exactement les pixels touchés.
