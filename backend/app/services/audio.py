"""Réception bornée et conversion locale avant création du brouillon privé."""

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import unquote

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from backend.app.audio_types import FORMATS, MAX_UPLOAD, AudioError
from backend.app.database import ROOT
from backend.app.storage.local import InvalidMedia, validate_filename

# Limite la réception + conversion à deux requêtes simultanées par processus.
UPLOAD_SLOTS = BoundedSemaphore(2)


def normalize(source: Path, target: Path, media_format: str) -> dict:
    """Le décodeur ne s'exécute jamais dans le processus HTTP et n'utilise pas de shell."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "backend.app.audio_worker",
             str(source), str(target), media_format],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=20, check=False,
        )
    except subprocess.TimeoutExpired:
        raise AudioError(422, "Le décodage a dépassé le délai autorisé de 20 secondes.") from None
    except OSError:
        raise AudioError(503, "Le décodeur audio local est indisponible.") from None
    if result.returncode == 3:
        raise AudioError(422, "L’audio dépasse la durée maximale de 8 minutes.")
    if result.returncode != 0 or len(result.stdout) > 1024:
        raise AudioError(415, "Le fichier n’est pas un audio valide dans un format accepté.")
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or set(data) != {
            "duration_ms", "sample_rate_hz", "channels", "sample_count",
        }:
            raise ValueError
        return data
    except (ValueError, TypeError):
        raise AudioError(503, "Réponse du décodeur audio invalide.") from None


def upload_parameters(request: Request) -> tuple[str, str]:
    """La déclaration du client sélectionne un décodeur, elle ne prouve pas le format."""
    media_format = request.headers.get("x-audio-format", "").lower()
    source_kind = request.headers.get("x-audio-source", "import")
    if media_format not in FORMATS or source_kind not in {"import", "microphone"}:
        raise AudioError(415, "Format audio non accepté.")
    if source_kind == "import" and media_format not in {"wav", "mp3"}:
        raise AudioError(415, "Importez un fichier WAV ou MP3.")
    raw_name = request.headers.get("x-audio-filename", "")
    if len(raw_name) > 1024:
        raise AudioError(400, "Nom de fichier refusé.")
    try:
        if raw_name:
            validate_filename(unquote(raw_name, errors="strict"), media_format)
    except (InvalidMedia, UnicodeError):
        raise AudioError(400, "Nom de fichier refusé.") from None
    return media_format, source_kind


async def receive_audio(request: Request, user_id, service):
    """Flux binaire brut : pas de chargement multipart intégral, pas de données avant validation."""
    media_format, source_kind = upload_parameters(request)
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > MAX_UPLOAD):
        raise AudioError(413, "L’audio doit faire au maximum 15 Mio.")
    if not UPLOAD_SLOTS.acquire(blocking=False):
        raise AudioError(429, "Deux imports sont déjà en cours. Réessayez dans un instant.")
    try:
        base = Path(tempfile.gettempdir()).resolve()
        if base.is_relative_to(ROOT) or any(p.lower().startswith("onedrive") for p in base.parts):
            raise AudioError(503, "Le dossier temporaire audio doit être privé et hors OneDrive.")
        with tempfile.TemporaryDirectory(prefix="dreams_audio_") as directory:
            source, target = Path(directory) / "source.bin", Path(directory) / "normalized.wav"
            received = 0
            try:
                async with asyncio.timeout(30):
                    with source.open("xb") as output:
                        async for chunk in request.stream():
                            received += len(chunk)
                            if received > MAX_UPLOAD:
                                raise AudioError(413, "L’audio doit faire au maximum 15 Mio.")
                            output.write(chunk)
            except (ClientDisconnect, TimeoutError):
                raise AudioError(408, "Envoi interrompu ou délai de 30 secondes dépassé.") from None
            if received == 0:
                raise AudioError(422, "Le fichier audio est vide.")
            if length is not None and received != int(length):
                raise AudioError(400, "Le transfert audio est incomplet.")
            data = await run_in_threadpool(normalize, source, target, media_format)
            metadata = {**data, "source_format": media_format,
                        "source_size_bytes": received, "audio_source": source_kind}
            with target.open("rb") as audio:
                return await run_in_threadpool(service.store_audio_draft, user_id, audio, metadata)
    except OSError:
        raise AudioError(503, "Enregistrement dans le stockage privé impossible.") from None
    finally:
        UPLOAD_SLOTS.release()
