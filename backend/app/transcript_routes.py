"""Édition du récit P06 : API Bearer et formulaire HTML protégé par CSRF."""

import asyncio
import uuid
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.requests import ClientDisconnect

from backend.app.auth import CurrentUser, Database
from backend.app.errors import error_response
from backend.app.models import Media, User
from backend.app.schemas import ErrorResponse
from backend.app.services.transcripts import TextVersionConflict, apply_correction, owned_dream
from backend.app.transcript_schemas import TranscriptResponse, TranscriptUpdate
from backend.app.web.routes import BrowserSession, render
from backend.app.web.security import check_csrf

router = APIRouter(tags=["Récit privé"], responses={
    401: {"model": ErrorResponse, "description": "Authentification requise."},
    409: {"model": ErrorResponse, "description": "Version dépassée ; recharger avant correction."},
})
MAX_FORM_BYTES = 256 * 1024


@router.get("/api/v1/dreams/{dream_id}/transcript", response_model=TranscriptResponse)
def read_transcript(dream_id: uuid.UUID, user: CurrentUser, db: Database):
    """Charge le texte et sa version, sans prétendre qu'une transcription a eu lieu."""
    return owned_dream(db, user.id, dream_id)


@router.patch("/api/v1/dreams/{dream_id}/transcript", response_model=TranscriptResponse)
def update_transcript(dream_id: uuid.UUID, payload: TranscriptUpdate,
                      user: CurrentUser, db: Database):
    """La version attendue évite d'écraser une correction concurrente."""
    dream = owned_dream(db, user.id, dream_id, lock=True)
    try:
        apply_correction(db, dream, payload.transcript, payload.expected_version)
    except TextVersionConflict:
        return error_response(409, "text_version_conflict", "Une correction plus récente existe.")
    db.commit()
    return dream


async def editor_form(request: Request) -> dict[str, str]:
    """Formulaire borné avant parsing ; aucun fichier, champ supplémentaire ou log du récit."""
    if request.headers.get("origin") != request.app.state.web_origin:
        raise HTTPException(403, "Origine refusée")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Formulaire non accepté")
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > MAX_FORM_BYTES:
        raise HTTPException(413, "Formulaire trop volumineux")
    body = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_FORM_BYTES:
                    raise HTTPException(413, "Formulaire trop volumineux")
                body.extend(chunk)
    except (ClientDisconnect, TimeoutError):
        raise HTTPException(408, "Formulaire interrompu") from None
    try:
        values = parse_qs(body.decode("ascii"), keep_blank_values=True, strict_parsing=True,
                          encoding="utf-8", errors="strict", max_num_fields=3)
        if set(values) != {"transcript", "expected_version", "csrf"}:
            raise ValueError
        if any(len(value) != 1 for value in values.values()):
            raise ValueError
        fields = {key: value[0] for key, value in values.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Formulaire invalide") from None
    check_csrf(request, fields["csrf"])
    return fields


def editor_response(request, db, dream, user_id, *, text=None, expected=None, error=None,
                     status=200):
    """Texte toujours échappé par Jinja ; les erreurs gardent la saisie soumise."""
    media = db.scalar(select(Media).where(
        Media.dream_id == dream.id, Media.kind == "audio", Media.storage_state == "ready",
        (Media.expires_at.is_(None) | (Media.expires_at > func.now())),
    ).order_by(Media.created_at.desc()).limit(1))
    value = (dream.transcript or "") if text is None else text
    saved = (not error and dream.transcript is not None
             and request.query_params.get("enregistre") == str(dream.text_version))
    return render(request, "transcript.html", status,
                  user=db.get(User, user_id), dream=dream, text=value, audio=media,
                  expected=dream.text_version if expected is None else expected,
                  error=error, saved=saved, unsaved=value != (dream.transcript or ""))


@router.get("/reves/{dream_id}/recit", include_in_schema=False)
def editor_page(dream_id: uuid.UUID, request: Request, session: BrowserSession, db: Database):
    """Un rêve existant suffit ; texte vide au départ, aucune simulation de STT."""
    dream = owned_dream(db, session.user_id, dream_id)
    return editor_response(request, db, dream, session.user_id)


@router.post("/reves/{dream_id}/recit", include_in_schema=False)
async def save_editor(dream_id: uuid.UUID, request: Request, session: BrowserSession, db: Database):
    """Sauvegarde explicite avec validation serveur et contrôle de version obligatoire."""
    fields = await editor_form(request)
    dream = owned_dream(db, session.user_id, dream_id, lock=True)
    try:
        raw_version = fields["expected_version"]
        if not raw_version.isascii() or not raw_version.isdigit() or len(raw_version) > 10:
            raise ValueError
        payload = TranscriptUpdate(
            transcript=fields["transcript"], expected_version=int(raw_version),
        )
    except (ValueError, ValidationError):
        return editor_response(
            request, db, dream, session.user_id, text=fields["transcript"],
            expected=fields["expected_version"], status=422,
            error="Saisissez un récit non vide de 20 000 caractères maximum et une version valide.",
        )
    try:
        apply_correction(db, dream, payload.transcript, payload.expected_version)
    except TextVersionConflict:
        return editor_response(
            request, db, dream, session.user_id, text=fields["transcript"],
            expected=payload.expected_version, status=409,
            error="Une autre correction a été enregistrée. Votre saisie est conservée ci-dessous. "
                  "Copiez-la si nécessaire avant de recharger la version actuelle.",
        )
    db.commit()
    return RedirectResponse(f"/reves/{dream.id}/recit?enregistre={dream.text_version}",
                            status_code=303)
