"""gsply : lecture / écriture de nuages de gaussiennes 3DGS.

Formats gérés
-------------
* PLY « Inria » (sortie de 3DGS original, PostShot, Nerfstudio/gsplat, Polycam, SuperSplat non compressé) :
  x y z [nx ny nz] f_dc_0..2 f_rest_0..(3K-1) opacity scale_0..2 rot_0..3
  - opacity est stockée en logit   -> alpha = sigmoid(opacity)
  - scale_i est stockée en log      -> sigma_i = exp(scale_i)
  - rot_0..3 = quaternion (w, x, y, z) non normalisé
  - f_rest est rangé canal par canal : f_rest[c*K + k] = coefficient k du canal c
* .splat (format « antimatter15 ») : 32 octets / gaussienne, sans harmoniques sphériques.

Dépendance : numpy uniquement.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

SH_C0 = 0.28209479177387814          # Y_0^0 = 1 / (2 sqrt(pi))
SH_REST_PER_DEGREE = {0: 0, 1: 3, 2: 8, 3: 15}  # coefficients « rest » par canal
DEGREE_FROM_REST = {v: k for k, v in SH_REST_PER_DEGREE.items()}

_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}
_NP_TO_PLY = {"i1": "char", "u1": "uchar", "i2": "short", "u2": "ushort",
              "i4": "int", "u4": "uint", "f4": "float", "f8": "double"}


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def logit(p, eps=1e-7):
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


@dataclass
class GaussianCloud:
    xyz: np.ndarray       # (N,3) positions
    f_dc: np.ndarray      # (N,3) coefficient SH d'ordre 0 (couleur de base)
    f_rest: np.ndarray    # (N,3,K) coefficients SH d'ordre >= 1, K in {0,3,8,15}
    opacity: np.ndarray   # (N,) logit de l'opacité
    scale: np.ndarray     # (N,3) log des écarts-types
    rot: np.ndarray       # (N,4) quaternion w,x,y,z
    extra: dict = field(default_factory=dict)  # autres propriétés scalaires (N,)

    # ---------------------------------------------------------------- infos
    def __len__(self):
        return self.xyz.shape[0]

    @property
    def sh_degree(self) -> int:
        return DEGREE_FROM_REST[self.f_rest.shape[2]]

    @property
    def alpha(self):
        return sigmoid(self.opacity)

    @property
    def sigma(self):
        return np.exp(self.scale)

    @property
    def rgb(self):
        """Couleur « diffuse » (ordre 0) dans [0,1]."""
        return np.clip(0.5 + SH_C0 * self.f_dc, 0.0, 1.0)

    def floats_per_gaussian(self, normals=False) -> int:
        return 3 + (3 if normals else 0) + 3 + 3 * self.f_rest.shape[2] + 1 + 3 + 4 + len(self.extra)

    # ---------------------------------------------------------- opérations
    def subset(self, sel) -> "GaussianCloud":
        return GaussianCloud(self.xyz[sel], self.f_dc[sel], self.f_rest[sel], self.opacity[sel],
                             self.scale[sel], self.rot[sel], {k: v[sel] for k, v in self.extra.items()})

    def copy(self) -> "GaussianCloud":
        return self.subset(slice(None))

    def normalized_rot(self):
        n = np.linalg.norm(self.rot, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return self.rot / n


# ======================================================================= PLY
def _read_header(f):
    first = f.readline().strip()
    if first != b"ply":
        raise ValueError("Ce fichier n'est pas un PLY")
    fmt, elements = None, []
    while True:
        line = f.readline()
        if not line:
            raise ValueError("En-tête PLY tronqué")
        tok = line.decode("ascii", "replace").strip().split()
        if not tok or tok[0] in ("comment", "obj_info"):
            continue
        if tok[0] == "format":
            fmt = tok[1]
        elif tok[0] == "element":
            elements.append({"name": tok[1], "count": int(tok[2]), "props": []})
        elif tok[0] == "property":
            if tok[1] == "list":
                raise ValueError("Propriétés 'list' non gérées (fichier maillage ?)")
            elements[-1]["props"].append((tok[2], _PLY_TYPES[tok[1]]))
        elif tok[0] == "end_header":
            break
    return fmt, elements


def read_ply_raw(path):
    """Retourne {nom_element: tableau structuré numpy}."""
    with open(path, "rb") as f:
        fmt, elements = _read_header(f)
        data = f.read()
    out, offset = {}, 0
    if fmt == "ascii":
        lines = data.decode("ascii").split("\n")
        li = 0
        for el in elements:
            dt = np.dtype([(n, t) for n, t in el["props"]])
            rows = [tuple(l.split()) for l in lines[li:li + el["count"]]]
            out[el["name"]] = np.array(rows, dtype=dt)
            li += el["count"]
        return out
    endian = {"binary_little_endian": "<", "binary_big_endian": ">"}[fmt]
    for el in elements:
        dt = np.dtype([(n, endian + t) for n, t in el["props"]])
        out[el["name"]] = np.frombuffer(data, dtype=dt, count=el["count"], offset=offset)
        offset += dt.itemsize * el["count"]
    return out


def read_ply(path) -> GaussianCloud:
    raw = read_ply_raw(path)
    if "chunk" in raw:
        raise ValueError("PLY compressé (SuperSplat / PlayCanvas) : décompressez-le d'abord, ex. "
                         "`npx @playcanvas/splat-transform in.compressed.ply out.ply`")
    if "vertex" not in raw:
        raise ValueError("Aucun élément 'vertex' dans le PLY")
    v = raw["vertex"]
    names = v.dtype.names
    f32 = lambda n: np.asarray(v[n], dtype=np.float32)
    N = len(v)

    xyz = np.stack([f32("x"), f32("y"), f32("z")], 1)
    if "f_dc_0" in names:
        f_dc = np.stack([f32(f"f_dc_{i}") for i in range(3)], 1)
    elif "red" in names:  # nuage de points coloré (ex. initialisation SfM)
        rgb = np.stack([f32("red"), f32("green"), f32("blue")], 1) / 255.0
        f_dc = (rgb - 0.5) / SH_C0
    else:
        raise ValueError("Pas de couleur (f_dc_* ou red/green/blue) : ce n'est pas un fichier 3DGS")

    rest_names = sorted([n for n in names if n.startswith("f_rest_")], key=lambda s: int(s[7:]))
    K = len(rest_names) // 3
    if K not in DEGREE_FROM_REST:
        raise ValueError(f"Nombre de coefficients f_rest inattendu : {len(rest_names)}")
    f_rest = (np.stack([f32(n) for n in rest_names], 1).reshape(N, 3, K) if K
              else np.zeros((N, 3, 0), np.float32))

    opacity = f32("opacity") if "opacity" in names else np.full(N, 4.0, np.float32)
    scale = (np.stack([f32(f"scale_{i}") for i in range(3)], 1) if "scale_0" in names
             else np.full((N, 3), np.log(0.01), np.float32))
    rot = (np.stack([f32(f"rot_{i}") for i in range(4)], 1) if "rot_0" in names
           else np.tile(np.array([1, 0, 0, 0], np.float32), (N, 1)))

    known = {"x", "y", "z", "nx", "ny", "nz", "opacity", "red", "green", "blue",
             *[f"f_dc_{i}" for i in range(3)], *rest_names,
             *[f"scale_{i}" for i in range(3)], *[f"rot_{i}" for i in range(4)]}
    extra = {n: np.array(v[n]) for n in names if n not in known}
    return GaussianCloud(xyz, f_dc, f_rest, opacity, scale, rot, extra)


def write_ply(path, g: GaussianCloud, normals: bool = False, keep_extra: bool = False):
    """Écrit un PLY binaire little-endian (format Inria).

    normals=False : les normales (toujours nulles en 3DGS) ne sont pas écrites -> -12 octets/gaussienne.
    """
    N, K = len(g), g.f_rest.shape[2]
    cols = [("x", g.xyz[:, 0]), ("y", g.xyz[:, 1]), ("z", g.xyz[:, 2])]
    if normals:
        z = np.zeros(N, np.float32)
        cols += [("nx", z), ("ny", z), ("nz", z)]
    cols += [(f"f_dc_{i}", g.f_dc[:, i]) for i in range(3)]
    rest = g.f_rest.reshape(N, 3 * K)
    cols += [(f"f_rest_{i}", rest[:, i]) for i in range(3 * K)]
    cols += [("opacity", g.opacity)]
    cols += [(f"scale_{i}", g.scale[:, i]) for i in range(3)]
    cols += [(f"rot_{i}", g.rot[:, i]) for i in range(4)]
    if keep_extra:
        cols += list(g.extra.items())

    dt = np.dtype([(n, "<f4" if not keep_extra or n not in g.extra else "<" + np.asarray(c).dtype.str[1:])
                   for n, c in cols])
    arr = np.empty(N, dtype=dt)
    for n, c in cols:
        arr[n] = c
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {N}"]
    header += [f"property {_NP_TO_PLY[dt[n].str[1:]]} {n}" for n, _ in cols]
    header += ["end_header"]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode("ascii"))
        f.write(arr.tobytes())


# ===================================================================== SPLAT
SPLAT_DTYPE = np.dtype([("pos", "<f4", 3), ("scale", "<f4", 3), ("rgba", "u1", 4), ("rot", "u1", 4)])


def write_splat(path, g: GaussianCloud):
    """Format .splat : position f32x3, échelle linéaire f32x3, RGBA u8x4, quaternion u8x4 (w,x,y,z).
    Les gaussiennes sont triées par « importance » décroissante (volume x opacité), comme le
    convertisseur de référence, ce qui permet un affichage progressif pertinent."""
    sig, a = g.sigma, g.alpha
    order = np.argsort(-(np.prod(sig, 1) * a))
    out = np.empty(len(g), SPLAT_DTYPE)
    out["pos"] = g.xyz[order]
    out["scale"] = sig[order]
    rgba = np.concatenate([g.rgb[order], a[order, None]], 1)
    out["rgba"] = np.clip(np.round(rgba * 255), 0, 255).astype(np.uint8)
    q = g.normalized_rot()[order]
    out["rot"] = np.clip(np.round(q * 128 + 128), 0, 255).astype(np.uint8)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    out.tofile(path)


def read_splat(path) -> GaussianCloud:
    d = np.fromfile(path, dtype=SPLAT_DTYPE)
    N = len(d)
    rgba = d["rgba"].astype(np.float32) / 255.0
    rot = (d["rot"].astype(np.float32) - 128.0) / 128.0
    return GaussianCloud(
        xyz=d["pos"].astype(np.float32),
        f_dc=((rgba[:, :3] - 0.5) / SH_C0).astype(np.float32),
        f_rest=np.zeros((N, 3, 0), np.float32),
        opacity=logit(rgba[:, 3]).astype(np.float32),
        scale=np.log(np.maximum(d["scale"], 1e-12)).astype(np.float32),
        rot=rot,
    )


# ===================================================================== utils
def load(path) -> GaussianCloud:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ply":
        return read_ply(path)
    if ext == ".splat":
        return read_splat(path)
    if ext == ".gsq":
        from gsq import decode_file
        return decode_file(path)
    raise ValueError(f"Extension non gérée : {ext}")


def save(path, g: GaussianCloud):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ply":
        write_ply(path, g)
    elif ext == ".splat":
        write_splat(path, g)
    else:
        raise ValueError(f"Extension non gérée : {ext}")


def human_size(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if abs(n) < 1024 or unit == "Go":
            return f"{n:.1f} {unit}" if unit != "o" else f"{int(n)} o"
        n /= 1024.0
