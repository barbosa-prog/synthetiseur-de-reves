"""Page audio, réception binaire authentifiée et confirmation privée P04."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.app.audio_types import AudioError
from backend.app.auth import CurrentUser, Database
from backend.app.errors import error_response
from backend.app.media_routes import Service
from backend.app.models import Dream, Media, User
from backend.app.schemas import ErrorResponse
from backend.app.services.audio import receive_audio
from backend.app.storage.local import StorageError
from backend.app.web.routes import BrowserSession, render
from backend.app.web.security import check_csrf

router = APIRouter(tags=["Audio"], responses={
    code: {"model": ErrorResponse, "description": description} for code, description in {
        400: "Transfert ou nom invalide", 401: "Authentification requise", 403: "CSRF refusé",
        408: "Envoi interrompu", 413: "Limite 15 Mio", 415: "Format audio refusé",
        422: "Audio vide ou trop long", 429: "Conversions occupées", 503: "Stockage indisponible",
    }.items()
})


class AudioResponse(BaseModel):
    """Identifiants publics et mesures, jamais une clé ou un chemin de stockage."""

    model_config = ConfigDict(extra="forbid")
    dream_id: uuid.UUID
    media_id: uuid.UUID
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_count: int
    source_format: str
    source_size_bytes: int
    audio_source: str


async def accept_audio(request: Request, user_id, service):
    """Réutilise la réception/conversion bornées et la publication privée P19."""
    try:
        return await receive_audio(request, user_id, service)
    except AudioError as exc:
        return error_response(exc.status, "audio_rejected", exc.message,
                              {"Retry-After": "5"} if exc.status == 429 else None)
    except StorageError:
        raise HTTPException(503, "Stockage privé indisponible") from None


@router.post("/api/v1/dreams/audio", response_model=AudioResponse, status_code=201,
             openapi_extra={
                 "requestBody": {"required": True, "content": {
                     "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
                 }},
                 "parameters": [
                     {"in": "header", "name": "X-Audio-Format", "required": True,
                      "schema": {"type": "string", "enum": ["wav", "mp3", "webm", "ogg", "mp4"]}},
                     {"in": "header", "name": "X-Audio-Source", "required": False,
                      "schema": {"type": "string", "enum": ["import", "microphone"],
                                 "default": "import"}},
                     {"in": "header", "name": "X-Audio-Filename", "required": False,
                      "schema": {"type": "string"},
                      "description": "Nom encodé en pourcentage, oublié après validation."},
                 ],
             })
async def api_upload(request: Request, user: CurrentUser, db: Database, service: Service):
    """Corps binaire WAV/MP3 ; en-têtes X-Audio-Format/Source/Filename, Bearer uniquement."""
    user_id = user.id
    db.rollback()  # libère la connexion d'authentification pendant l'envoi/décodage
    return await accept_audio(request, user_id, service)


@router.post("/web/audio", response_model=AudioResponse, status_code=201, include_in_schema=False)
async def browser_upload(request: Request, session: BrowserSession, db: Database, service: Service):
    """Cookie HTTPS et preuve CSRF en en-tête avant toute lecture du corps audio."""
    check_csrf(request, request.headers.get("x-csrf-token", ""))
    user_id = session.user_id
    db.rollback()
    return await accept_audio(request, user_id, service)


@router.get("/nouveau-reve", include_in_schema=False)
def capture_page(request: Request, session: BrowserSession, db: Database):
    """Capture guidée sans transcription ni historique."""
    return render(request, "audio.html", user=db.get(User, session.user_id),
                  expires_at=session.expires_at.isoformat())


@router.get("/reves/{dream_id}/audio", include_in_schema=False)
def audio_confirmation(dream_id: uuid.UUID, request: Request,
                       session: BrowserSession, db: Database):
    """Consultation de l'audio P04 existant et de ses mesures privées."""
    media = db.scalar(select(Media).join(Dream).where(
        Dream.id == dream_id, Dream.user_id == session.user_id, Dream.status != "deleted",
        Media.kind == "audio", Media.storage_state == "ready", Media.audio_source.is_not(None),
    ).order_by(Media.created_at.desc()).limit(1))
    if media is None:
        raise HTTPException(404, "Audio inaccessible")
    return render(request, "audio_ready.html", media=media,
                  user=db.get(User, session.user_id), expires_at=session.expires_at.isoformat())
