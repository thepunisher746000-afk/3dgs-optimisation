# Benchmark — scene_A014

2026-11-25 14:31 · entrée 122.4 Mo · 517 513 gaussiennes · 6 vues de test 400×300 · durée 855.0 s

| Famille | Variante | Taille | Facteur | PSNR (pire) | SSIM | Surdessin | Pareto |
|---|---|---|---|---|---|---|---|
| Référence | original | 116.5 Mo | ×1.1 | 50.00 (50.00) | 1.0000 | 54.4 |  |
| Nettoyage | nettoyage_moyen | 103.2 Mo | ×1.2 | 35.44 (27.13) | 0.9764 | 49.8 |  |
| Nettoyage | nettoyage_leger | 116.5 Mo | ×1.1 | 50.00 (50.00) | 1.0000 | 54.4 |  |
| Nettoyage | nettoyage_agressif | 89.7 Mo | ×1.4 | 24.68 (17.74) | 0.9035 | 45.3 |  |
| Élagage | proxy_75 | 87.4 Mo | ×1.4 | 32.41 (26.35) | 0.9662 | 47.5 |  |
| Élagage | proxy_50 | 58.2 Mo | ×2.1 | 25.35 (21.14) | 0.8531 | 42.0 |  |
| Élagage | proxy_35_comp | 40.8 Mo | ×3.0 | 25.30 (21.25) | 0.8325 | 37.7 |  |
| Élagage | views_75 | 87.4 Mo | ×1.4 | 36.09 (30.59) | 0.9753 | 51.9 |  |
| Élagage | views_50 | 58.2 Mo | ×2.1 | 29.03 (25.59) | 0.9201 | 47.4 |  |
| Élagage | views_35 | 40.8 Mo | ×3.0 | 25.45 (22.79) | 0.8562 | 43.0 |  |
| Élagage | views_50_comp | 58.2 Mo | ×2.1 | 31.17 (27.00) | 0.9346 | 46.3 |  |
| Élagage | views_35_comp | 40.8 Mo | ×3.0 | 28.19 (24.71) | 0.8915 | 42.4 |  |
| Élagage | views_20_comp | 29.0 Mo | ×4.2 | 25.97 (23.06) | 0.8474 | 39.1 |  |
| Couleurs (SH) | sh_2 | 75.0 Mo | ×1.6 | 39.27 (37.52) | 0.9923 | 54.4 |  |
| Couleurs (SH) | sh_1 | 45.4 Mo | ×2.7 | 34.36 (32.38) | 0.9784 | 54.4 |  |
| Couleurs (SH) | sh_0 | 27.6 Mo | ×4.4 | 31.75 (30.10) | 0.9648 | 54.4 |  |
| Quantification | gsq_vq | 8.6 Mo | ×14.3 | 41.44 (39.97) | 0.9910 | 54.4 | ★ |
| Quantification | gsq_8bit | 23.0 Mo | ×5.3 | 50.00 (50.00) | 0.9997 | 54.4 | ★ |
| Quantification | gsq_vq_compact | 7.1 Mo | ×17.2 | 39.40 (38.13) | 0.9871 | 54.4 | ★ |
| Combinaisons | views75_gsq | 6.5 Mo | ×18.8 | 35.86 (30.87) | 0.9696 | 51.4 | ★ |
| Combinaisons | views50_sh1_gsq | 4.2 Mo | ×29.1 | 29.31 (26.43) | 0.9161 | 46.3 | ★ |
| Combinaisons | views35_gsq | 3.0 Mo | ×41.1 | 27.98 (24.57) | 0.8843 | 42.4 | ★ |
| Formats existants | splat_antimatter15 | 15.8 Mo | ×7.8 | 31.58 (30.10) | 0.9641 | 54.4 |  |
| Formats existants | playcanvas_compressed_ply | — | — | skipped : splat-transform non installé (npm install -g @playcanvas/splat-transform) | | | |
| Formats existants | playcanvas_sog | — | — | skipped : splat-transform non installé (npm install -g @playcanvas/splat-transform) | | | |

## Analyse

- **Plus petit fichier avec PSNR ≥ 35 dB** : `views75_gsq` — 6.5 Mo (×18.8 par rapport à l'entrée), 35.9 dB
- **Plus petit fichier avec PSNR ≥ 30 dB** : `views75_gsq` — 6.5 Mo (×18.8 par rapport à l'entrée), 35.9 dB
- **Nettoyage** : surdessin 54 → 45 fragments/pixel (÷1.2) avec `nettoyage_agressif`, PSNR 24.7 dB : effet modeste sur le coût d'affichage pour cette scène (peu de floaters).

Efficacité de chaque famille (taille comparée au modèle de référence ; PSNR borné à 50 dB = aucune différence mesurable) :

| Famille | Variante la plus efficace | dB perdus par division de la taille par 2 | Gain de taille | PSNR |
|---|---|---|---|---|
| Élagage | `views_20_comp` | 11.99 | ×4.0 | 26.0 dB |
| Couleurs (SH) | `sh_0` | 8.80 | ×4.2 | 31.7 dB |
| Quantification | `gsq_8bit` | 0.00 | ×5.1 | 50.0 dB |
| Combinaisons | `views75_gsq` | 3.40 | ×17.9 | 35.9 dB |
| Formats existants | `splat_antimatter15` | 6.39 | ×7.4 | 31.6 dB |
