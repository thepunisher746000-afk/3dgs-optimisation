# Benchmark — synthetic

2026-11-17 13:50 · entrée 71.0 Mo · 300 000 gaussiennes · 6 vues de test 400×300 · durée 849.1 s

| Famille | Variante | Taille | Facteur | PSNR (pire) | SSIM | Surdessin | Pareto |
|---|---|---|---|---|---|---|---|
| Référence | original | 67.5 Mo | ×1.1 | 9.44 (8.79) | 0.3885 | 209.5 |  |
| Référence | nettoye_moyen | 60.8 Mo | ×1.2 | 50.00 (50.00) | 1.0000 | 30.2 |  |
| Nettoyage | nettoyage_leger | 64.5 Mo | ×1.1 | 9.44 (8.79) | 0.3885 | 209.5 |  |
| Nettoyage | nettoyage_agressif | 56.3 Mo | ×1.3 | 37.45 (32.06) | 0.9786 | 25.2 |  |
| Élagage | proxy_75 | 45.6 Mo | ×1.6 | 31.19 (30.61) | 0.9382 | 25.1 |  |
| Élagage | proxy_50 | 30.4 Mo | ×2.3 | 24.86 (24.22) | 0.8129 | 20.8 |  |
| Élagage | proxy_35_comp | 21.3 Mo | ×3.3 | 28.66 (27.77) | 0.9123 | 21.5 |  |
| Élagage | views_75 | 45.6 Mo | ×1.6 | 38.38 (35.66) | 0.9790 | 25.4 |  |
| Élagage | views_50 | 30.4 Mo | ×2.3 | 32.67 (31.64) | 0.9547 | 23.0 |  |
| Élagage | views_35 | 21.3 Mo | ×3.3 | 28.22 (27.39) | 0.8978 | 20.6 |  |
| Élagage | views_50_comp | 30.4 Mo | ×2.3 | 34.14 (31.91) | 0.9673 | 23.0 |  |
| Élagage | views_35_comp | 21.3 Mo | ×3.3 | 31.26 (29.38) | 0.9440 | 21.0 |  |
| Élagage | views_20_comp | 12.4 Mo | ×5.7 | 28.17 (27.24) | 0.9056 | 18.4 |  |
| Couleurs (SH) | sh_2 | 39.1 Mo | ×1.8 | 50.00 (50.00) | 0.9997 | 30.2 |  |
| Couleurs (SH) | sh_1 | 23.7 Mo | ×3.0 | 48.35 (45.36) | 0.9946 | 30.2 |  |
| Couleurs (SH) | sh_0 | 14.4 Mo | ×4.9 | 40.99 (39.11) | 0.9658 | 30.2 |  |
| Quantification | gsq_vq | 3.5 Mo | ×20.3 | 45.07 (43.48) | 0.9881 | 30.2 | ★ |
| Quantification | gsq_8bit | 8.0 Mo | ×8.8 | 50.00 (50.00) | 0.9998 | 30.2 | ★ |
| Quantification | gsq_vq_compact | 2.5 Mo | ×28.1 | 44.03 (42.45) | 0.9852 | 30.2 | ★ |
| Combinaisons | views75_gsq | 2.3 Mo | ×30.4 | 38.09 (36.81) | 0.9680 | 25.4 | ★ |
| Combinaisons | views50_sh1_gsq | 1.4 Mo | ×49.4 | 33.79 (31.80) | 0.9563 | 23.0 | ★ |
| Combinaisons | views35_gsq | 1.1 Mo | ×64.6 | 31.11 (29.33) | 0.9356 | 21.0 | ★ |
| Formats existants | splat_antimatter15 | 8.2 Mo | ×8.6 | 40.98 (39.11) | 0.9658 | 30.2 |  |
| Formats existants | playcanvas_compressed_ply | — | — | skipped : splat-transform non installé (npm install -g @playcanvas/splat-transform) | | | |
| Formats existants | playcanvas_sog | — | — | skipped : splat-transform non installé (npm install -g @playcanvas/splat-transform) | | | |

## Analyse

- **Plus petit fichier avec PSNR ≥ 35 dB** : `views75_gsq` — 2.3 Mo (×30.4 par rapport à l'entrée), 38.1 dB
- **Plus petit fichier avec PSNR ≥ 30 dB** : `views35_gsq` — 1.1 Mo (×64.6 par rapport à l'entrée), 31.1 dB
- **Nettoyage** : surdessin 210 → 25 fragments/pixel (÷8.3) avec `nettoyage_agressif`, PSNR 37.4 dB : c'est lui qui rend l'affichage fluide.

Efficacité de chaque famille (taille comparée au modèle de référence ; PSNR borné à 50 dB = aucune différence mesurable) :

| Famille | Variante la plus efficace | dB perdus par division de la taille par 2 | Gain de taille | PSNR |
|---|---|---|---|---|
| Élagage | `views_20_comp` | 9.51 | ×4.9 | 28.2 dB |
| Couleurs (SH) | `sh_2` | 0.00 | ×1.6 | 50.0 dB |
| Quantification | `gsq_8bit` | 0.00 | ×7.6 | 50.0 dB |
| Combinaisons | `views75_gsq` | 2.53 | ×26.0 | 38.1 dB |
| Formats existants | `splat_antimatter15` | 3.13 | ×7.4 | 41.0 dB |
