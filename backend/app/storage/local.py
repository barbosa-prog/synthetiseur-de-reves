"""Stockage plat local : clés opaques, validation et publication atomique sans écrasement."""

import hashlib
import io
import os
import re
import secrets
import stat
import warnings
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from mutagen.mp3 import MP3
from PIL import Image

from backend.app.database import ROOT

MAX_AUDIO = 15 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
KEY = re.compile(r"[a-f0-9]{64}\Z")
MARKER = ".private-store-v1"
FORMATS = {"wav": ("audio", "audio/wav"), "mp3": ("audio", "audio/mpeg"),
           "png": ("image", "image/png"), "jpeg": ("image", "image/jpeg"),
           "webp": ("image", "image/webp")}


class StorageError(Exception):
    """Erreur publique sans chemin, nom de fichier ni contenu privé."""


class MissingObject(StorageError):
    """Objet absent, distingué d'un objet dangereux pour l'export P10."""


class InvalidMedia(StorageError):
    """Format, taille ou contenu refusé."""


@dataclass(frozen=True)
class StoredObject:
    """Métadonnées internes ; jamais sérialisées directement vers le navigateur."""

    key: str
    size: int
    media_type: str
    sha256: str


@dataclass(frozen=True)
class InventoryEntry:
    """Candidat de maintenance, sans chemin absolu."""

    key: str
    temporary: bool
    modified_at: float


class PrivateStorage(Protocol):
    """Contrat réutilisable par les futurs adaptateurs et services."""

    def write(self, source: BinaryIO, *, key: str, kind: str, media_format: str,
              filename: str | None = None) -> StoredObject: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str, *, temporary: bool = False) -> None: ...
    def is_absent(self, key: str, *, temporary: bool = False) -> bool: ...
    def inventory(self) -> list[InventoryEntry]: ...


def new_key() -> str:
    """256 bits aléatoires, sans identifiant utilisateur ni nom original."""
    return secrets.token_hex(32)


def has_reparse(path: Path) -> bool:
    """Refuse les symlinks et les jonctions/reparse points Windows."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
    )


def validate_filename(filename: str | None, media_format: str) -> None:
    """Nom optionnel vérifié puis oublié ; il n'est jamais utilisé pour écrire."""
    if filename is None:
        return
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    extension = filename.rsplit(".", 1)[-1].lower()
    if (not filename or len(filename) > 128 or any(ord(c) < 32 for c in filename)
            or any(c in filename for c in '/\\:<>"|?*') or ".." in filename
            or filename.endswith((".", " ")) or filename.split(".")[0].upper() in reserved
            or extension not in ({"jpg", "jpeg"} if media_format == "jpeg" else {media_format})):
        raise InvalidMedia("Nom de fichier refusé.")


def validate_payload(payload: bytes, media_format: str) -> None:
    """Décode les images/WAV ; contrôle la structure MPEG du MP3, sans moteur STT."""
    try:
        if media_format in {"png", "jpeg", "webp"}:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(payload)) as image:
                    if (image.format.lower() != media_format
                            or image.width * image.height > MAX_PIXELS):
                        raise ValueError
                    if getattr(image, "n_frames", 1) != 1:
                        raise ValueError
                    image.verify()
                with Image.open(io.BytesIO(payload)) as image:
                    image.load()
        elif media_format == "wav":
            with wave.open(io.BytesIO(payload), "rb") as audio:
                count = audio.getnframes()
                if (count <= 0 or audio.getnchannels() not in {1, 2}
                        or not 8000 <= audio.getframerate() <= 192000
                        or audio.getsampwidth() not in {1, 2, 3, 4}):
                    raise ValueError
                expected = count * audio.getnchannels() * audio.getsampwidth()
                if len(audio.readframes(count)) != expected:
                    raise ValueError
        elif media_format == "mp3":
            info = MP3(io.BytesIO(payload)).info
            if info.layer != 3 or info.length <= 0 or info.sample_rate <= 0 or info.sketchy:
                raise ValueError
        else:
            raise ValueError
    except Exception:
        raise InvalidMedia("Contenu média invalide ou format incohérent.") from None


class LocalPrivateStorage:
    """Répertoire local dédié, hors dépôt/OneDrive, jamais monté comme ressource HTTP."""

    def __init__(self, root: Path):
        if not root.is_absolute():
            raise StorageError("Le stockage exige un dossier absolu privé.")
        self.root = root
        self._guard()

    @classmethod
    def from_environment(cls):
        """Aucune création de dossier lors du démarrage de l'API."""
        configured = os.getenv("PRIVATE_MEDIA_ROOT")
        if configured:
            return cls(Path(configured))
        if os.name == "nt":
            base = os.getenv("LOCALAPPDATA")
            if not base:
                raise StorageError("Définir PRIVATE_MEDIA_ROOT hors du dépôt et de OneDrive.")
            return cls(Path(base) / "SynthetiseurDeReves" / "private_media")
        return cls(Path.home() / ".local/share/synthetiseur-de-reves/private_media")

    def _guard(self) -> None:
        try:
            for path in [self.root, *self.root.parents]:
                if path.exists() or path.is_symlink():
                    if has_reparse(path):
                        raise ValueError
            resolved = self.root.resolve()
            if resolved == resolved.parent or self.root.drive.startswith("\\\\"):
                raise ValueError
            if resolved.is_relative_to(ROOT.resolve()) or any(
                part.lower().startswith("onedrive") for part in resolved.parts
            ):
                raise ValueError
            for variable in ["OneDrive", "OneDriveCommercial", "OneDriveConsumer"]:
                if (os.getenv(variable)
                        and resolved.is_relative_to(Path(os.environ[variable]).resolve())):
                    raise ValueError
            if self.root.exists():
                marker = self.root / MARKER
                if marker.exists():
                    if has_reparse(marker) or not marker.is_dir():
                        raise ValueError
                elif any(self.root.iterdir()):
                    # Ne jamais adopter un dossier arbitraire déjà rempli.
                    raise ValueError
        except (OSError, ValueError):
            raise StorageError("Dossier de stockage refusé ou inaccessible.") from None

    def _path(self, key: str, temporary: bool = False) -> Path:
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise StorageError("Clé de stockage invalide.")
        self._guard()
        path = self.root / (f".{key}.tmp" if temporary else key)
        try:
            if path.exists() or path.is_symlink():
                if has_reparse(path) or not stat.S_ISREG(path.lstat().st_mode):
                    raise StorageError("Objet de stockage refusé.")
        except OSError:
            raise StorageError("Objet de stockage inaccessible.") from None
        return path

    def write(self, source: BinaryIO, *, key: str, kind: str, media_format: str,
              filename: str | None = None) -> StoredObject:
        """Valide avant écriture, puis publie par lien atomique sans écrasement."""
        if media_format not in FORMATS or FORMATS[media_format][0] != kind:
            raise InvalidMedia("Type de média non accepté.")
        validate_filename(filename, media_format)
        limit = MAX_AUDIO if kind == "audio" else MAX_IMAGE
        payload = bytearray()
        try:
            while chunk := source.read(min(65536, limit + 1 - len(payload))):
                if not isinstance(chunk, bytes):
                    raise ValueError
                payload.extend(chunk)
                if len(payload) > limit:
                    raise InvalidMedia("Média trop volumineux.")
        except InvalidMedia:
            raise
        except Exception:
            raise StorageError("Lecture de la source impossible.") from None
        if not payload:
            raise InvalidMedia("Média vide.")
        validate_payload(bytes(payload), media_format)
        target, staged = self._path(key), self._path(key, True)
        owns_stage, published = False, False
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._guard()
            (self.root / MARKER).mkdir(mode=0o700, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(staged, flags, 0o600)
            owns_stage = True
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.link(staged, target, follow_symlinks=False)
            published = True
            staged.unlink()
            owns_stage = False
        except OSError:
            # Ne jamais remplacer un objet préexistant en cas de collision.
            try:
                if published:
                    target.unlink(missing_ok=True)
                if owns_stage:
                    staged.unlink(missing_ok=True)
            except OSError:
                pass  # une maintenance avec délai de grâce détectera le staging résiduel
            raise StorageError("Écriture du média impossible.") from None
        return StoredObject(key, len(payload), FORMATS[media_format][1],
                            hashlib.sha256(payload).hexdigest())

    def open(self, key: str) -> BinaryIO:
        """Retourne un descripteur déjà ouvert ; aucun FileResponse réouvrant un chemin."""
        path = self._path(key)
        handle = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            handle = os.fdopen(os.open(path, flags), "rb")
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or has_reparse(path):
                handle.close()
                raise StorageError("Objet de stockage refusé.")
            return handle
        except FileNotFoundError:
            if handle is not None:
                handle.close()
            raise MissingObject("Média privé absent.") from None
        except OSError:
            if handle is not None:
                handle.close()
            raise StorageError("Média privé indisponible.") from None

    def delete(self, key: str, *, temporary: bool = False) -> None:
        """Suppression idempotente d'une clé interne, jamais d'un chemin fourni."""
        path = self._path(key, temporary)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise StorageError("Suppression du média différée.") from None

    def is_absent(self, key: str, *, temporary: bool = False) -> bool:
        """Absence confirmée, jamais déduite d'un refus d'accès ou d'un lien."""
        path = self._path(key, temporary)
        try:
            info = path.lstat()
            if info.st_nlink != 1:
                raise StorageError("Objet de stockage refusé.")
            return False
        except FileNotFoundError:
            return True
        except OSError:
            raise StorageError("État du média indisponible.") from None

    def inventory(self) -> list[InventoryEntry]:
        """N'énumère que des fichiers réguliers conformes au format interne."""
        self._guard()
        if not self.root.exists():
            return []
        result = []
        try:
            with os.scandir(self.root) as entries:
                for entry in entries:
                    temporary = entry.name.startswith(".") and entry.name.endswith(".tmp")
                    key = entry.name[1:-4] if temporary else entry.name
                    if KEY.fullmatch(key) and entry.is_file(follow_symlinks=False):
                        if not has_reparse(Path(entry.path)):
                            result.append(InventoryEntry(key, temporary, entry.stat().st_mtime))
        except OSError:
            raise StorageError("Inventaire privé indisponible.") from None
        return result
