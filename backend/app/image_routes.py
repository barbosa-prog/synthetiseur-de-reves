"""P07 : demandes explicites privées et suivi léger ; aucun moteur IA dans FastAPI."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from backend.app.auth import CurrentUser, Database
from backend.app.errors import error_response
from backend.app.media_routes import Service
from backend.app.models import ImageDescription, ImageGeneration, Job, User
from backend.app.services import image_jobs
from backend.app.services.image_execution import current_image
from backend.app.services.transcripts import owned_dream
from backend.app.transcript_routes import editor_form
from backend.app.web.routes import BrowserSession, render

router = APIRouter(tags=["Images privées"])
MESSAGES = {
    "queued": "En attente du worker image local.",
    "running": "Génération en cours…",
    "done": "Image terminée.",
    "outdated": "Résultat dépassé : le récit ou la description a changé.",
    "failed": "La génération a échoué. Vous pouvez réessayer explicitement.",
    "safety_blocked": "Le filtre de sécurité a bloqué la sortie. Aucune image publiée.",
    "timeout": "Le délai de génération est dépassé. Aucun nouvel essai automatique.",
    "insufficient_memory": "Mémoire insuffisante sur le PC. Libérez des ressources puis réessayez.",
    "cancelled": "La demande a été annulée.",
    "worker_stopped": "Le worker a été interrompu. Vérifiez son démarrage avant de réessayer.",
}


class DescriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=500, repr=False)
    text_version: int = Field(ge=1, le=2147483646, strict=True)
    expected_version: int = Field(ge=0, le=2147483646, strict=True)


class ImageStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_version: int = Field(ge=1, le=2147483646, strict=True)
    description_version: int = Field(ge=1, le=2147483646, strict=True)


def state(db, user_id, dream_id, job=None):
    from backend.app.services.job_lifecycle import bounded
    bounded(db)
    dream = owned_dream(db, user_id, dream_id, lock=True)
    description = db.get(ImageDescription, dream_id, populate_existing=True)
    if job is None:
        job = db.scalar(select(Job).where(Job.dream_id == dream_id, Job.kind == "image")
                        .order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
    ready = bool(description and dream.transcript
                 and description.text_version == dream.text_version)
    result = {"job_id": job.id if job else None, "status": "idle", "message": "Aucune demande.",
              "busy": False, "ready": ready, "text_version": dream.text_version,
              "description_version": description.version if description else 0, "image_url": None}
    if job:
        snapshot = db.get(ImageGeneration, job.id)
        stale = (not snapshot or not ready or snapshot.text_version != dream.text_version
                 or snapshot.description_version != description.version)
        status = "outdated" if stale or job.error_code == "text_conflict" else job.status
        result.update(status=status, busy=job.status in {"queued", "running"},
                      message=MESSAGES.get(status, MESSAGES["failed"]))
        if status == "failed":
            result["message"] = MESSAGES.get(job.error_code, MESSAGES["failed"])
    media_id = current_image(db, user_id, dream_id)
    if media_id:
        result["image_url"] = f"/web/media/{media_id}/content"
    from backend.app.services.job_tracking import project
    result["tracking"] = project(db, user_id, job) if job else None
    if result["tracking"] and result["tracking"]["outdated"]:
        result.update(status="outdated", message=MESSAGES["outdated"], image_url=None)
    return result


@router.get("/api/v1/dreams/{dream_id}/image-description")
def description_api(dream_id: uuid.UUID, user: CurrentUser, db: Database):
    dream = owned_dream(db, user.id, dream_id)
    description = image_jobs.description_for(db, user.id, dream_id)
    return {"description": description.description if description else "",
            "version": description.version if description else 0,
            "text_version": dream.text_version,
            "source_text_version": description.text_version if description else None}


@router.put("/api/v1/dreams/{dream_id}/image-description")
def save_api(dream_id: uuid.UUID, payload: DescriptionUpdate, user: CurrentUser, db: Database):
    try:
        image_jobs.save_description(db, user.id, dream_id, payload.description,
                                    payload.text_version, payload.expected_version)
    except ValidationError:
        raise HTTPException(422, "Description invalide : 1 à 500 caractères") from None
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return error_response(409, "image_version_conflict", "Récit ou description à recharger.")
    return description_api(dream_id, user, db)


@router.post("/api/v1/dreams/{dream_id}/images", status_code=202)
def start_api(dream_id: uuid.UUID, payload: ImageStart, user: CurrentUser, db: Database,
              service: Service):
    try:
        job = image_jobs.enqueue(db, user.id, dream_id, payload.text_version,
                                 payload.description_version, media_service=service)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return error_response(409, "image_conflict", "Demande active ou versions à recharger.")
    result = state(db, user.id, dream_id, job)
    if result["image_url"]:
        result["image_url"] = result["image_url"].replace("/web/media/", "/api/v1/media/")
    return result


@router.get("/api/v1/images/{job_id}")
def status_api(job_id: uuid.UUID, user: CurrentUser, db: Database):
    job = image_jobs.owned_job(db, user.id, job_id)
    result = state(db, user.id, job.dream_id, job)
    if result["image_url"]:
        result["image_url"] = result["image_url"].replace("/web/media/", "/api/v1/media/")
    return result


def page(request, db, user_id, dream_id, *, error=None, status=200, submitted=None):
    dream = owned_dream(db, user_id, dream_id)
    description = image_jobs.description_for(db, user_id, dream_id)
    return render(request, "image.html", status, dream=dream, user=db.get(User, user_id),
                  description=description, progress=state(db, user_id, dream_id), error=error,
                  submitted=submitted)


@router.get("/reves/{dream_id}/image", include_in_schema=False)
def image_page(dream_id: uuid.UUID, request: Request, session: BrowserSession, db: Database):
    return page(request, db, session.user_id, dream_id)


def versions(raw):
    parts = raw.split(":")
    if len(parts) != 2 or any(not p.isascii() or not p.isdigit() or len(p) > 10 for p in parts):
        raise ValueError
    return int(parts[0]), int(parts[1])


@router.post("/reves/{dream_id}/image/description", include_in_schema=False)
async def save_web(dream_id: uuid.UUID, request: Request, session: BrowserSession, db: Database):
    fields = await editor_form(request, {"description", "expected_version", "csrf"})
    owned_dream(db, session.user_id, dream_id)
    try:
        text_version, expected = versions(fields["expected_version"])
        payload = DescriptionUpdate(description=fields["description"], text_version=text_version,
                                    expected_version=expected)
        image_jobs.save_description(db, session.user_id, dream_id, payload.description,
                                    text_version, expected)
    except (ValueError, ValidationError):
        return page(request, db, session.user_id, dream_id, status=422,
                    error="Description invalide : 1 à 500 caractères non vides.",
                    submitted=fields["description"])
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        db.rollback()
        return page(request, db, session.user_id, dream_id, status=409,
                    error=exc.detail, submitted=fields["description"])
    return RedirectResponse(f"/reves/{dream_id}/image?enregistre=1", status_code=303)


@router.post("/reves/{dream_id}/image/generer", include_in_schema=False)
async def start_web(dream_id: uuid.UUID, request: Request, session: BrowserSession, db: Database,
                    service: Service):
    fields = await editor_form(request, {"expected_version", "csrf"})
    owned_dream(db, session.user_id, dream_id)
    try:
        text_version, description_version = versions(fields["expected_version"])
        payload = ImageStart(text_version=text_version, description_version=description_version)
        image_jobs.enqueue(db, session.user_id, dream_id, payload.text_version,
                           payload.description_version, media_service=service)
    except (ValueError, ValidationError):
        return page(request, db, session.user_id, dream_id, status=422,
                    error="Enregistrez une description liée au récit courant.")
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        db.rollback()
        return page(request, db, session.user_id, dream_id, status=409, error=exc.detail)
    return RedirectResponse(f"/reves/{dream_id}/image", status_code=303)


@router.get("/reves/{dream_id}/image/statut", include_in_schema=False)
def status_web(dream_id: uuid.UUID, session: BrowserSession, db: Database):
    return state(db, session.user_id, dream_id)
