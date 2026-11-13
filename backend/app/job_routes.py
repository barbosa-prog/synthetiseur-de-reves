"""Relances P11 explicites : Bearer API ou session/CSRF, jamais de modèle IA."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from backend.app.auth import CurrentUser, Database
from backend.app.media_routes import Service
from backend.app.services import job_tracking as tracking
from backend.app.transcript_routes import editor_form
from backend.app.web.routes import BrowserSession

router = APIRouter(tags=["Relances explicites P11"])
PAGES = {"stt": "transcription", "image": "image", "emotion": "emotion"}


def response(db, owner, identifier, kind):
    job = tracking.owned_job(db, owner, identifier, kind)
    if kind == "stt":
        from backend.app.services.stt_jobs import projection
        return projection(job, db, owner)
    if kind == "emotion":
        from backend.app.services.emotions import job_projection
        return job_projection(db, owner, identifier)
    from backend.app.image_routes import state
    result = state(db, owner, job.dream_id, job)
    if result["image_url"]:
        result["image_url"] = result["image_url"].replace("/web/media/", "/api/v1/media/")
    return result


@router.post("/api/v1/transcriptions/{job_id}/retry", status_code=202)
def retry_stt(job_id: UUID, payload: tracking.RetryInput, user: CurrentUser, db: Database):
    tracking.mutate(db, user.id, job_id, "stt", payload)
    return response(db, user.id, job_id, "stt")


@router.post("/api/v1/images/{job_id}/retry", status_code=202)
def retry_image(job_id: UUID, payload: tracking.RetryInput, user: CurrentUser, db: Database):
    tracking.mutate(db, user.id, job_id, "image", payload)
    return response(db, user.id, job_id, "image")


@router.post("/api/v1/emotion-jobs/{job_id}/retry", status_code=202)
def retry_emotion(job_id: UUID, payload: tracking.RetryInput, user: CurrentUser, db: Database):
    tracking.mutate(db, user.id, job_id, "emotion", payload)
    return response(db, user.id, job_id, "emotion")


@router.post("/api/v1/images/{job_id}/regenerate", status_code=202)
def regenerate_image(job_id: UUID, payload: tracking.RetryInput, user: CurrentUser,
                     db: Database, service: Service):
    identifier = tracking.mutate(db, user.id, job_id, "image", payload,
                                 regenerate=True, media_service=service)
    return response(db, user.id, identifier, "image")


@router.post("/reves/{dream_id}/traitements/{kind}/{job_id}/{action}", include_in_schema=False)
async def web_action(dream_id: UUID, kind: str, job_id: UUID, action: str, request: Request,
                     session: BrowserSession, db: Database):
    if kind not in PAGES or action not in {"relancer", "regenerer"} or (
        action == "regenerer" and kind != "image"
    ):
        raise HTTPException(404, "Action introuvable")
    job = tracking.owned_job(db, session.user_id, job_id, kind)
    if job.dream_id != dream_id:
        raise HTTPException(404, "Traitement inaccessible")
    fields = await editor_form(request, {"csrf", "expected", "confirmed"})
    try:
        parts = fields["expected"].split(":")
        if len(parts) != 4 or any(not p.isascii() or not p.isdigit() or len(p) > 10 for p in parts):
            raise ValueError
        version, description, choice, retries = map(int, parts)
        payload = tracking.RetryInput(confirmed=fields["confirmed"] == "yes",
            expected_text_version=version, expected_retry_count=retries,
            expected_description_version=description if kind == "image" else None,
            expected_choice_revision=choice if kind == "emotion" else None)
        tracking.mutate(db, session.user_id, job_id, kind, payload,
                        regenerate=action == "regenerer")
    except (ValueError, ValidationError):
        raise HTTPException(422, "Confirmation invalide ; rechargez la page.") from None
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        db.rollback()
        message = "Action refusée : vérifiez les versions et le budget, puis rechargez la page."
        if kind == "image":
            from backend.app.image_routes import page
            return page(request, db, session.user_id, dream_id, error=message, status=409)
        if kind == "emotion":
            from backend.app.emotion_web import page
            return page(request, db, session, dream_id, error=message, status=409)
        from backend.app.services.transcripts import owned_dream
        from backend.app.stt_routes import page
        return page(request, db, owned_dream(db, session.user_id, dream_id), session,
                    error=message, status=409)
    return RedirectResponse(f"/reves/{dream_id}/{PAGES[kind]}", status_code=303)
