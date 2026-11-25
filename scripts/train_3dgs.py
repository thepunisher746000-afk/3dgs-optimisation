#!/usr/bin/env python3
"""Génère un modèle 3DGS à partir d'un dossier de photos, avec l'outil d'entraînement disponible.

Backends (détectés dans le PATH, par ordre de préférence) :
  * nerfstudio : ns-process-data (COLMAP intégré) -> ns-train splatfacto -> ns-export gaussian-splat
  * colmap + opensplat : colmap automatic_reconstructor (poses) -> opensplat (entraînement)
Sinon : message expliquant comment générer le modèle avec PostShot / Polycam / Brush à partir des
images extraites, puis l'importer dans le portail.

    python3 scripts/train_3dgs.py data/captures/salle --iterations 7000
Résultat : data/<nom>.ply (+ poses caméras pour l'élagage « poses de capture » quand l'outil les fournit).

ATTENTION : ce script n'a pas pu être testé dans l'environnement de développement (aucun outil
d'entraînement installé). Les commandes suivent la documentation de chaque outil ; vérifier les
options de la version installée en cas d'erreur.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys


# Environnements Python où chercher nerfstudio en plus du PATH (le portail ne les « active » pas) :
# variable GS_VENV, puis ~/venvs/torch (environnement installé pour ce projet).
VENVS = [os.environ.get("GS_VENV", ""), os.path.expanduser("~/venvs/torch")]


def tool(name):
    """Chemin d'un exécutable : PATH d'abord, puis bin/ des environnements connus."""
    found = shutil.which(name)
    if found:
        return found
    for v in VENVS:
        p = os.path.join(v, "bin", name)
        if v and os.access(p, os.X_OK):
            return p
    return None


def run(cmd, cwd=None):
    print("$ " + " ".join(cmd), flush=True)
    env = dict(os.environ)
    for v in VENVS:  # les commandes ns-* appellent colmap/ffmpeg via le PATH : on y ajoute l'environnement
        if v and os.path.isdir(os.path.join(v, "bin")):
            env["PATH"] = os.path.join(v, "bin") + os.pathsep + env.get("PATH", "")
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode:
        sys.exit(f"échec ({r.returncode}) : {' '.join(cmd)}")


def downscaled_copy(src, dst, max_side):
    """Copies réduites (côté max = max_side) en gardant l'EXIF (focale utile à COLMAP).
    Sans cela, l'extraction SIFT de COLMAP sur des photos de 12 Mpx dépasse vite la RAM de WSL."""
    from PIL import Image, ImageOps
    os.makedirs(dst, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(src)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        out = os.path.join(dst, f)
        if os.path.exists(out):
            n += 1
            continue
        im = Image.open(os.path.join(src, f))
        exif = im.info.get("exif")
        im = ImageOps.exif_transpose(im)  # pixels redressés : l'orientation n'est plus à appliquer
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        if exif:
            ex = Image.Exif()
            ex.load(exif)
            ex[0x0112] = 1  # orientation normale
            im.save(out, quality=95, exif=ex.tobytes())
        else:
            im.save(out, quality=95)
        n += 1
    return n


def export_nerfstudio_cameras(proc, outputs, dest):
    """Poses des photos -> data/<scène>_cameras.json, dans le repère du .ply exporté et en convention
    OpenCV (x droite, y bas, z avant), lisible par prune.py --cameras et benchmark.py --cameras.

    Conversion vérifiée sur la scène A014 (rendu depuis ces poses : 22-27 dB contre les photos) :
      c2w_ply = T_dataparser · A⁻¹ · c2w_transforms, translation x scale, puis axes y et z inversés
    où A = « applied_transform » de transforms.json et (T, scale) = dataparser_transforms.json."""
    import json
    import numpy as np
    t = json.load(open(os.path.join(proc, "transforms.json")))
    dps = sorted(glob.glob(os.path.join(outputs, "**", "dataparser_transforms.json"), recursive=True), key=os.path.getmtime)
    if not dps:
        print("dataparser_transforms.json introuvable : poses non exportées")
        return
    dp = json.load(open(dps[-1]))
    T = np.vstack([np.array(dp["transform"]), [0, 0, 0, 1]])
    Ainv = np.eye(4)
    if "applied_transform" in t:
        Ainv[:3, :3] = np.array(t["applied_transform"])[:, :3].T
    cams = []
    for f in sorted(t["frames"], key=lambda f: f["file_path"]):
        c2w = T @ Ainv @ np.vstack([np.array(f["transform_matrix"])[:3], [0, 0, 0, 1]])
        c2w[:3, 3] *= dp["scale"]
        R = (c2w[:3, :3] @ np.diag([1, -1, -1])).T          # monde -> caméra, convention OpenCV
        cams.append({"name": os.path.basename(f["file_path"]), "R": R.tolist(), "t": (-R @ c2w[:3, 3]).tolist(),
                     "fx": f.get("fl_x", t["fl_x"]), "fy": f.get("fl_y", t["fl_y"]), "cx": f.get("cx", t["cx"]),
                     "cy": f.get("cy", t["cy"]), "w": f.get("w", t["w"]), "h": f.get("h", t["h"])})
    with open(dest, "w") as fh:
        json.dump({"format": "gs-cameras-v1", "convention": "opencv world->camera", "cameras": cams}, fh)
    print(f"{len(cams)} poses caméras -> {dest}")


def available_backends():
    out = []
    # ffmpeg sert à ns-process-data pour réduire les images (pip install imageio-ffmpeg suffit, cf. README)
    if tool("ns-train") and tool("ns-process-data") and tool("ns-export") and tool("colmap") and tool("ffmpeg"):
        out.append("nerfstudio")
    if tool("colmap") and tool("opensplat"):
        out.append("opensplat")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", help="dossier de capture contenant images/")
    ap.add_argument("--iterations", type=int, default=7000, help="7000 = rapide ; 30000 = qualité de l'article")
    ap.add_argument("--backend", choices=("auto", "nerfstudio", "opensplat"), default="auto")
    ap.add_argument("--images", default=None,
                    help="sous-dossier d'images à utiliser (défaut : postshot_input/ s'il existe — images vérifiées — sinon images/)")
    ap.add_argument("--colmap-gpu", action="store_true", help="SIFT de COLMAP sur GPU (COLMAP compilé avec CUDA seulement)")
    ap.add_argument("--matching", choices=("exhaustive", "sequential", "vocab_tree"), default="exhaustive",
                    help="exhaustive : toutes les paires (sûr jusqu'à ~300 images) ; sequential : vidéo")
    ap.add_argument("--cameras-only", action="store_true",
                    help="ré-exporte seulement les poses caméras d'un entraînement nerfstudio déjà fait")
    ap.add_argument("--max-size", type=int, default=1600,
                    help="côté max des images avant COLMAP/entraînement (RAM et VRAM limitées ; 0 = taille d'origine)")
    args = ap.parse_args()

    cap = os.path.abspath(args.capture)
    if args.cameras_only:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        name = os.path.basename(cap.rstrip("/"))
        export_nerfstudio_cameras(os.path.join(cap, "work", "ns"), os.path.join(cap, "work", "outputs"),
                                  os.path.join(root, "data", f"{name}_cameras.json"))
        return
    sub = args.images or ("postshot_input" if os.path.isdir(os.path.join(cap, "postshot_input")) else "images")
    images = os.path.join(cap, sub)
    n_img = len([f for f in os.listdir(images)]) if os.path.isdir(images) else 0
    if n_img < 20:
        sys.exit(f"Seulement {n_img} images dans {images} : il en faut au moins 20 (idéalement 100 à 300).")
    name = os.path.basename(cap.rstrip("/"))
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dest = os.path.join(root, "data", f"{name}.ply")
    backends = available_backends()
    backend = backends[0] if args.backend == "auto" and backends else args.backend
    print(f"{n_img} images ; outils d'entraînement détectés : {', '.join(backends) or 'aucun'}")

    if backend == "auto" or backend not in backends:
        print("\nAucun outil d'entraînement 3DGS utilisable ici. Pour générer le modèle :\n"
              f"  1. PostShot (Windows + GPU NVIDIA) : importer {images} (ou la vidéo d'origine), entraîner,\n"
              "     exporter en .ply ;\n"
              "  2. Polycam / Luma (cloud) : envoyer les photos (bouton « Archive ZIP » du portail) ;\n"
              "  3. Brush (Windows / Linux / macOS) : ouvrir le dossier de capture ;\n"
              "  4. ou installer COLMAP (sudo apt install colmap) et nerfstudio dans ~/venvs/torch\n"
              f"     (manquant ici : {', '.join(t for t in ('colmap', 'ns-train', 'ffmpeg') if not tool(t)) or '—'}), puis relancer.\n"
              "Puis importer le .ply obtenu dans l'onglet Modèles.")
        sys.exit(2)

    work = os.path.join(cap, "work")
    os.makedirs(work, exist_ok=True)
    if backend == "nerfstudio":
        proc = os.path.join(work, "ns")
        if os.path.exists(os.path.join(proc, "transforms.json")):
            print(f"Poses déjà calculées ({proc}/transforms.json) : étape COLMAP sautée")
        else:
            src = images
            if args.max_size:
                src = os.path.join(work, f"input_{args.max_size}")
                k = downscaled_copy(images, src, args.max_size)
                print(f"{k} images réduites à {args.max_size} px max dans {src}")
            # 1. poses par COLMAP (via nerfstudio) ; images réduites ×2, ×4 en plus pour l'entraînement
            shutil.rmtree(proc, ignore_errors=True)  # reste d'un essai interrompu
            run([tool("ns-process-data"), "images", "--data", src, "--output-dir", proc,
                 "--matching-method", args.matching, "--num-downscales", "2"]
                + ([] if args.colmap_gpu else ["--no-gpu"]))
        # 2. entraînement splatfacto. Images gardées en RAM (pas en mémoire GPU) : indispensable sous 8 Go de VRAM.
        #    Le chargeur nerfstudio choisit seul la réduction (côté max <= 1600 px).
        run([tool("ns-train"), "splatfacto", "--data", proc, "--output-dir", os.path.join(work, "outputs"),
             "--max-num-iterations", str(args.iterations), "--viewer.quit-on-train-completion", "True",
             "--vis", "tensorboard", "--pipeline.datamanager.cache-images", "cpu"])
        cfgs = sorted(glob.glob(os.path.join(work, "outputs", "**", "config.yml"), recursive=True), key=os.path.getmtime)
        if not cfgs:
            sys.exit("config.yml introuvable après l'entraînement")
        run([tool("ns-export"), "gaussian-splat", "--load-config", cfgs[-1], "--output-dir", os.path.join(work, "export")])
        plys = glob.glob(os.path.join(work, "export", "*.ply"))
        if not plys:
            sys.exit("aucun .ply exporté")
        shutil.copy(plys[0], dest)
        export_nerfstudio_cameras(proc, os.path.join(work, "outputs"), dest[:-4] + "_cameras.json")
    else:  # colmap + opensplat
        run([tool("colmap"), "automatic_reconstructor", "--workspace_path", cap, "--image_path", images, "--dense", "0"])
        run([tool("opensplat"), cap, "-n", str(args.iterations), "-o", dest])
        print(f"Poses caméras COLMAP : {os.path.join(cap, 'sparse', '0')} (export texte : colmap model_converter)")
    print(f"\nModèle généré : {dest}")


if __name__ == "__main__":
    main()
