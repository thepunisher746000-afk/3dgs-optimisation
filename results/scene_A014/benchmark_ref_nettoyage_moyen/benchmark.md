# Benchmark — scene_A014

2026-11-25 14:16 · entrée 122.4 Mo · 517 513 gaussiennes · 6 vues de test 400×300 · durée 756.0 s

| Famille | Variante | Taille | Facteur | PSNR (pire) | SSIM | Surdessin | Pareto |
|---|---|---|---|---|---|---|---|
| Référence | original | 116.5 Mo | ×1.1 | 35.44 (27.13) | 0.9764 | 54.4 |  |
| Référence | nettoye_moyen | 103.2 Mo | ×1.2 | 50.00 (50.00) | 1.0000 | 49.8 |  |
| Nettoyage | nettoyage_leger | 116.5 Mo | ×1.1 | 35.44 (27.13) | 0.9764 | 54.4 |  |
| Nettoyage | nettoyage_agressif | 89.7 Mo | ×1.4 | 25.71 (19.26) | 0.9256 | 45.3 |  |
| Élagage | proxy_75 | 77.4 Mo | ×1.6 | 33.10 (27.53) | 0.9713 | 43.0 |  |
| Élagage | proxy_50 | 51.6 Mo | ×2.4 | 25.94 (21.79) | 0.8761 | 36.3 |  |
| Élagage | proxy_35_comp | 36.1 Mo | ×3.4 | 25.10 (21.65) | 0.8420 | 33.0 |  |
| Élagage | views_75 | 77.4 Mo | ×1.6 | 35.71 (29.47) | 0.9761 | 47.1 |  |
| Élagage | views_50 | 51.6 Mo | ×2.4 | 28.04 (23.65) | 0.9121 | 41.9 |  |
| Élagage | views_35 | 36.1 Mo | ×3.4 | 23.80 (20.27) | 0.8307 | 37.0 |  |
| Élagage | views_50_comp | 51.6 Mo | ×2.4 | 30.65 (25.60) | 0.9328 | 41.9 |  |
| Élagage | views_35_comp | 36.1 Mo | ×3.4 | 27.33 (23.15) | 0.8825 | 37.7 |  |
| Élagage | views_20_comp | 25.8 Mo | ×4.8 | 25.32 (21.78) | 0.8371 | 34.3 |  |
| Couleurs (SH) | sh_2 | 66.5 Mo | ×1.8 | 39.29 (37.54) | 0.9925 | 49.8 |  |
| Couleurs (SH) | sh_1 | 40.2 Mo | ×3.0 | 34.40 (32.42) | 0.9790 | 49.8 |  |
| Couleurs (SH) | sh_0 | 24.5 Mo | ×5.0 | 31.79 (30.15) | 0.9658 | 49.8 |  |
| Quantification | gsq_vq | 7.6 Mo | ×16.2 | 41.87 (39.82) | 0.9914 | 49.8 | ★ |
| Quantification | gsq_8bit | 20.5 Mo | ×6.0 | 50.00 (50.00) | 0.9997 | 49.8 | ★ |
| Quantification | gsq_vq_compact | 6.3 Mo | ×19.5 | 39.66 (37.77) | 0.9877 | 49.8 | ★ |
| Combinaisons | views75_gsq | 5.8 Mo | ×21.2 | 35.94 (30.16) | 0.9711 | 46.9 | ★ |
| Combinaisons | views50_sh1_gsq | 3.7 Mo | ×33.0 | 28.94 (25.21) | 0.9148 | 41.9 | ★ |
| Combinaisons | views35_gsq | 2.6 Mo | ×46.2 | 27.16 (23.05) | 0.8757 | 37.8 | ★ |
| Formats existants | splat_antimatter15 | 14.0 Mo | ×8.7 | 31.62 (30.15) | 0.9652 | 49.8 |  |
| Formats existants | playcanvas_compressed_ply | — | — | skipped : splat-transform non installé (npm install -g @playcanvas/splat-transform) | | | |
| Formats existants | playcanvas_sog | — | — | skipped : splat-transform non installé (npm install -g @playcanvas/splat-transform) | | | |

## Analyse

- **Plus petit fichier avec PSNR ≥ 35 dB** : `views75_gsq` — 5.8 Mo (×21.2 par rapport à l'entrée), 35.9 dB
- **Plus petit fichier avec PSNR ≥ 30 dB** : `views75_gsq` — 5.8 Mo (×21.2 par rapport à l'entrée), 35.9 dB
- **Nettoyage** : surdessin 54 → 45 fragments/pixel (÷1.2) avec `nettoyage_agressif` : c'est lui qui rend l'affichage fluide ; son effet sur la taille est faible.

Efficacité de chaque famille (taille comparée à la référence nettoyée ; PSNR borné à 50 dB = aucune différence mesurable) :

| Famille | Variante la plus efficace | dB perdus par division de la taille par 2 | Gain de taille | PSNR |
|---|---|---|---|---|
| Élagage | `views_20_comp` | 12.32 | ×4.0 | 25.3 dB |
| Couleurs (SH) | `sh_0` | 8.77 | ×4.2 | 31.8 dB |
| Quantification | `gsq_8bit` | 0.00 | ×5.0 | 50.0 dB |
| Combinaisons | `views75_gsq` | 3.38 | ×17.9 | 35.9 dB |
| Formats existants | `splat_antimatter15` | 6.37 | ×7.4 | 31.6 dB |
