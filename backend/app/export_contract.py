"""P10 : contrat sans ZIP, accès disque, route HTTP ou dépendance IA."""

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import BinaryIO
from uuid import UUID


class ExportError(Exception):
    """Code public stable ; aucune donnée privée dans l'exception."""


@dataclass(frozen=True)
class ExportLimits:
    max_media: int = 100
    max_bytes: int = 100 * 1024**2

    def __post_init__(self):
        if (type(self.max_media) is not int or not 1 <= self.max_media <= 100
                or type(self.max_bytes) is not int or not 1 <= self.max_bytes <= 100 * 1024**2):
            raise ExportError("invalid_limits")

    @classmethod
    def from_environment(cls):
        try:
            return cls(int(os.getenv("EXPORT_MAX_MEDIA", "100")),
                       int(os.getenv("EXPORT_MAX_BYTES", str(100 * 1024**2))))
        except ValueError:
            raise ExportError("invalid_limits") from None


EXTENSIONS = {"audio/wav": "wav", "audio/mpeg": "mp3", "image/png": "png",
              "image/jpeg": "jpg", "image/webp": "webp"}
ROOT_FILES = ("README.txt", "recit.txt", "reve.json", "manifest.json")
README = (
    "Export d'un seul rêve. Textes UTF-8 et métadonnées JSON.\n"
    "Seul le récit courant est fourni ; les instantanés techniques ne constituent "
    "pas un historique exhaustif des révisions.\n"
    "La suggestion IA est indicative, non médicale et distincte du choix retenu.\n"
    "Consulter manifest.json pour les médias absents ou non vérifiés.\n"
)


def media_name(identifier: UUID, kind: str, media_type: str) -> str:
    if not isinstance(identifier, UUID) or kind not in {"audio", "image", "sound"}:
        raise ExportError("invalid_media")
    if media_type not in EXTENSIONS or (
        (kind == "image") != media_type.startswith("image/")
    ):
        raise ExportError("invalid_media")
    return f"medias/{kind}-{identifier}.{EXTENSIONS[media_type]}"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ExportSelection:
    """Document immuable ; empreinte interne non sérialisée dans l'export."""

    document_json: str = field(repr=False)
    fingerprint: str = field(repr=False)

    def documents(self) -> dict[str, bytes]:
        document = json.loads(self.document_json)
        return {
            "README.txt": README.encode("utf-8"),
            "recit.txt": (document["dream"]["transcript"] or "").encode("utf-8"),
            "reve.json": json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"),
            "manifest.json": json.dumps(
                {"format_version": 1, "media": document["media"]},
                ensure_ascii=False, indent=2,
            ).encode("utf-8"),
        }


def check_integrity(stream: BinaryIO, size: int, sha256: str) -> str:
    """Contrat du futur lecteur : flux borné, aucun contenu renvoyé ni journalisé."""
    if type(size) is not int or size < 1 or size > 15 * 1024**2:
        return "integrity_error"
    digest, count = hashlib.sha256(), 0
    while chunk := stream.read(min(65536, size + 1 - count)):
        count += len(chunk)
        if count > size:
            return "integrity_error"
        digest.update(chunk)
    return "verified" if count == size and digest.hexdigest() == sha256 else "integrity_error"
