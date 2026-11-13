"""Déclenchement explicite et suivi privé ; aucun moteur IA dans FastAPI."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from backend.app.auth import CurrentUser, Database
from backend.app.models import Job, Media, User
from backend.app.services.stt_jobs import enqueue, owned_job, projection
from backend.app.services.transcripts import owned_dream
from backend.app.transcript_routes import editor_form
from backend.app.web.routes import BrowserSession, render

router = APIRouter(tags=["Transcription locale"])


class StartTranscription(BaseModel):
    """Version obligatoire même si le récit est encore vide."""

    model_config = ConfigDict(extra="forbid")
    media_id: uuid.UUID
    expected_version: int = Field(ge=0, le=2147483646, strict=True)


@router.post("/api/v1/dreams/{dream_id}/transcriptions", status_code=202)
def start_api(dream_id: uuid.UUID, payload: StartTranscription, user: CurrentUser, db: Database):
    return projection(enqueue(db, user.id, dream_id, payload.media_id, payload.expected_version),
                      db, user.id)


@router.get("/api/v1/transcriptions/{job_id}")
def status_api(job_id: uuid.UUID, user: CurrentUser, db: Database):
    return projection(owned_job(db, user.id, job_id), db, user.id)


def page(request, db, dream, session, *, error=None, status=200):
    media = db.scalar(select(Media).where(
        Media.dream_id == dream.id, Media.kind == "audio", Media.storage_state == "ready",
        Media.audio_source.is_not(None),
        (Media.expires_at.is_(None) | (Media.expires_at > func.now())),
    ).order_by(Media.created_at.desc()).limit(1))
    job = db.scalar(select(Job).where(Job.dream_id == dream.id, Job.kind == "stt").order_by(
        Job.created_at.desc(), Job.id.desc(),
    ).limit(1))
    return render(request, "transcription.html", status, dream=dream, media=media,
                  job=projection(job, db, dream.user_id) if job else None, error=error,
                  user=db.get(User, dream.user_id), expires_at=session.expires_at.isoformat())


@router.get("/reves/{dream_id}/transcription", include_in_schema=False)
def transcription_page(dream_id: uuid.UUID, request: Request,
                       session: BrowserSession, db: Database):
    return page(request, db, owned_dream(db, session.user_id, dream_id), session)


@router.post("/reves/{dream_id}/transcription", include_in_schema=False)
async def transcription_submit(dream_id: uuid.UUID, request: Request,
                               session: BrowserSession, db: Database):
    fields = await editor_form(request, {"media_id", "expected_version", "csrf"})
    dream = owned_dream(db, session.user_id, dream_id)
    try:
        raw = fields["expected_version"]
        if not raw.isascii() or not raw.isdigit() or len(raw) > 10:
            raise ValueError
        payload = StartTranscription(media_id=fields["media_id"], expected_version=int(raw))
    except (ValueError, ValidationError):
        return page(request, db, dream, session,
                    error="Demande invalide ; rechargez la page.", status=422)
    try:
        enqueue(db, session.user_id, dream_id, payload.media_id, payload.expected_version)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return page(request, db, dream, session, error=exc.detail, status=409)
    return RedirectResponse(f"/reves/{dream_id}/transcription", status_code=303)


@router.get("/reves/{dream_id}/transcription/{job_id}", include_in_schema=False)
def status_web(dream_id: uuid.UUID, job_id: uuid.UUID, session: BrowserSession, db: Database):
    job = owned_job(db, session.user_id, job_id)
    if job.dream_id != dream_id:
        raise HTTPException(404, "Traitement inaccessible")
    return projection(job, db, session.user_id)
