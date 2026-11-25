#!/usr/bin/env python3
"""Détection du type d'un fichier importé, d'après son CONTENU (octets d'en-tête, propriétés PLY)
et pas seulement son extension : un .ply peut être un modèle 3DGS, un PLY compressé PlayCanvas, un
simple nuage de points (sortie COLMAP) ou un maillage ; un .mp4 peut en réalité être un .mov, etc.

    python3 scripts/formats.py fichier [fichier ...]
"""
import gzip
import json
import os
import re
import struct
import sys
import zipfile

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".insv")
MODEL_EXT = (".ply", ".splat", ".ksplat", ".spz", ".sog", ".gsq")
UPLOAD_EXT = MODEL_EXT + VIDEO_EXT + IMAGE_EXT + (".zip",)

# kind -> (libellé, catégorie). Catégories : model (modèle 3DGS exploitable), capture (matière première
# à transformer en modèle), other (reconnu mais non exploitable tel quel), unknown.
KINDS = {
    "gaussians": ("Modèle 3DGS (PLY)", "model"),
    "gaussians_compressed": ("Modèle 3DGS compressé (PlayCanvas compressed.ply)", "model"),
    "splat": ("Modèle 3DGS (.splat)", "model"),
    "ksplat": ("Modèle 3DGS (.ksplat)", "model"),
    "spz": ("Modèle 3DGS (SPZ, Niantic)", "model"),
    "sog": ("Modèle 3DGS (SOG, PlayCanvas)", "model"),
    "gsq": ("Modèle 3DGS compressé (GSQ, ce projet)", "model"),
    "video": ("Vidéo de capture", "capture"),
    "image": ("Photo de capture", "capture"),
    "image_archive": ("Archive de photos", "capture"),
    "pointcloud": ("Nuage de points (pas un modèle 3DGS)", "other"),
    "mesh": ("Maillage 3D (pas un modèle 3DGS)", "other"),
    "archive": ("Archive ZIP (sans photos)", "other"),
    "unknown": ("Format non reconnu", "unknown"),
}


def _ply_header(head):
    end = head.find(b"end_header")
    if end < 0:
        return None
    text = head[:end].decode("ascii", "replace")
    elements, props = [], {}
    for line in text.splitlines():
        t = line.split()
        if t[:1] == ["element"]:
            elements.append((t[1], int(t[2])))
            props[t[1]] = []
        elif t[:1] == ["property"] and elements:
            props[elements[-1][0]].append(t[-1])
    return elements, props


def detect(path):
    """Retourne {"kind", "label", "category", "details": {...}}."""
    name = os.path.basename(path).lower()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(65536)
    det = {}
    kind = "unknown"

    if head.startswith(b"ply"):
        h = _ply_header(head)
        if h:
            elements, props = h
            ecount = dict(elements)
            vp = set(props.get("vertex", []))
            if "chunk" in ecount:
                kind = "gaussians_compressed"
                det["n"] = ecount.get("vertex")
            elif {"opacity", "scale_0", "rot_0"} <= vp or "f_dc_0" in vp:
                kind = "gaussians"
                rest = sum(1 for p in vp if p.startswith("f_rest_"))
                det.update(n=ecount.get("vertex"), sh_degree={0: 0, 9: 1, 24: 2, 45: 3}.get(rest, "?"))
            elif "face" in ecount:
                kind = "mesh"
                det.update(vertices=ecount.get("vertex"), faces=ecount.get("face"))
            elif "vertex" in ecount:
                kind = "pointcloud"
                det.update(n=ecount.get("vertex"), colors={"red", "green", "blue"} <= vp)
    elif head[:4] == b"GSQ1":
        kind = "gsq"
        n = struct.unpack("<I", head[4:8])[0]
        det["n"] = json.loads(head[8:8 + n]).get("n")
    elif head[:2] == b"\x1f\x8b":                                   # gzip : SPZ = gzip(en-tête "NGSP" ...)
        try:
            with gzip.open(path, "rb") as gz:
                inner = gz.read(16)
            if inner[:4] == b"NGSP":
                kind = "spz"
                det["n"] = struct.unpack("<I", inner[8:12])[0]
        except OSError:
            pass
    elif head[4:8] == b"ftyp":                                      # conteneur ISO : MP4 / MOV / HEIC
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
            kind = "image"
        else:
            kind = "video"
            det["container"] = "QuickTime/MOV" if brand == b"qt  " else "MP4"
    elif head[:4] == b"\x1aE\xdf\xa3":
        kind, det["container"] = "video", "Matroska/WebM"
    elif head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        kind, det["container"] = "video", "AVI"
    elif head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or head[:4] in (b"II*\x00", b"MM\x00*") \
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        kind = "image"
    elif head[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
            imgs = [n for n in names if n.lower().endswith(IMAGE_EXT)]
            if name.endswith(".sog") or "meta.json" in names:
                kind = "sog"
            elif imgs:
                kind, det["images"] = "image_archive", len(imgs)
            else:
                kind, det["entries"] = "archive", len(names)
        except zipfile.BadZipFile:
            pass
    elif name.endswith(".ksplat"):
        kind = "ksplat"
    elif name.endswith(".splat") and size % 32 == 0:
        kind = "splat"
        det["n"] = size // 32

    if kind == "video":
        det.update(_video_info(path))
    label, category = KINDS[kind]
    return {"kind": kind, "label": label, "category": category, "details": det, "size": size}


def _video_info(path):
    try:
        import cv2
    except ImportError:
        return {}
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"readable": False}
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    info = {"readable": True, "fps": round(fps, 2), "frames": n,
            "duration_s": round(n / fps, 1) if fps else None,
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    cap.release()
    return info


def safe_stem(name):
    stem = re.sub(r"\.(gsq\.ply|compressed\.ply|[^.]+)$", "", os.path.basename(name), flags=re.I)
    return re.sub(r"[^\w\-]+", "_", stem).strip("_") or "capture"


if __name__ == "__main__":
    for p in sys.argv[1:]:
        d = detect(p)
        print(f"{p}: {d['label']} {d['details']}")
