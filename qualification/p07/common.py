"""Configuration du prototype isolé, sans import du backend ni accès au .env."""

import ctypes
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

REPOSITORY = "stable-diffusion-v1-5/stable-diffusion-v1-5"
REVISION = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"
WEIGHTS = {
    "safety_checker/model.fp16.safetensors": 608018440,
    "text_encoder/model.fp16.safetensors": 246144864,
    "unet/diffusion_pytorch_model.fp16.safetensors": 1719125304,
    "vae/diffusion_pytorch_model.fp16.safetensors": 167335342,
}
FILES = [*WEIGHTS, "model_index.json", "README.md",
         "feature_extractor/preprocessor_config.json", "safety_checker/config.json",
         "scheduler/scheduler_config.json", "text_encoder/config.json",
         "tokenizer/merges.txt", "tokenizer/special_tokens_map.json",
         "tokenizer/tokenizer_config.json", "tokenizer/vocab.json", "unet/config.json",
         "vae/config.json"]
PINS = {"torch": "2.7.1+cu118", "torchvision": "0.22.1+cu118", "diffusers": "0.35.2",
        "transformers": "4.57.6", "accelerate": "1.12.0", "huggingface-hub": "0.36.0",
        "safetensors": "0.7.0", "numpy": "2.2.6", "Pillow": "11.3.0",
        "tokenizers": "0.22.2", "psutil": "7.1.3"}


class QualificationError(ValueError):
    """Message statique du prototype, sans contenu de dépendance ou chemin privé."""


def paths():
    """Aucune création de dossier avant l'exécution explicite autorisée."""
    if sys.platform != "win32" or not os.getenv("LOCALAPPDATA"):
        raise QualificationError("Prototype Windows : LOCALAPPDATA requis.")
    root = (Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/p07-qualification").resolve()
    workspace = Path(__file__).resolve().parents[2]
    if root.is_relative_to(workspace) or any("onedrive" in part.lower() for part in root.parts):
        raise QualificationError("Le prototype doit rester hors du dépôt et de OneDrive.")
    return root, root / "venv", root / "model", root / "results"


def ram_mib():
    """Lecture Windows uniquement ; aucun chargement de bibliothèque IA."""
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in (
                "total", "available", "page_total", "page_available", "virtual_total",
                "virtual_available", "extended",
            )
        ]
    state = Memory()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise QualificationError("Mesure RAM indisponible.")
    return state.available // 1024**2


def gpu_info():
    """nvidia-smi : aucune initialisation de modèle ni allocation CUDA."""
    response = subprocess.run([
        "nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    ], capture_output=True, text=True, timeout=10, check=True)
    fields = response.stdout.splitlines()[0].split(",")
    name, total, free, driver = [part.strip() for part in fields]
    return {"name": name, "total_mib": int(total), "free_mib": int(free), "driver": driver}


def versions():
    result = {}
    for name in PINS:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def require_environment():
    if Path(sys.prefix).resolve() != paths()[1]:
        raise QualificationError("Utiliser uniquement le Python du venv de qualification séparé.")
    if sys.version_info[:2] != (3, 12):
        raise QualificationError("Python 3.12 requis.")
    if versions() != PINS:
        raise QualificationError("Versions différentes ; vérifier pip check et les pins.")


def require_memory(mode):
    """Marges prudentes de qualification, sans modifier les limites P05."""
    minimum_ram = 6144 if mode == "gpu" else 8192
    minimum_vram = 4096 if mode == "gpu" else 2048
    if ram_mib() < minimum_ram or gpu_info()["free_mib"] < minimum_vram:
        raise QualificationError("Mémoire insuffisante : libérer RAM/VRAM avant cet essai.")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_model():
    """Lecture locale exclusivement ; jamais de récupération de poids manquants."""
    model = paths()[2]
    manifest = json.loads((model / "qualification-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("revision") != REVISION or set(manifest.get("files", {})) != set(FILES):
        raise QualificationError("Manifest du modèle invalide.")
    for name, expected_hash in manifest["files"].items():
        item = model / name
        if not item.is_file() or digest(item) != expected_hash:
            raise QualificationError("Modèle incomplet ou empreinte incorrecte.")
        if name in WEIGHTS and item.stat().st_size != WEIGHTS[name]:
            raise QualificationError("Taille des poids incorrecte.")
    return model


@contextmanager
def exclusive():
    """Un seul téléchargement ou benchmark à la fois ; verrou explicite après crash."""
    root = paths()[0]
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "qualification.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def free_disk_gib():
    return round(shutil.disk_usage(paths()[0].anchor).free / 1024**3, 2)
