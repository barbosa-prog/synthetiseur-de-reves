"""P08 web : session/CSRF, services partagés, aucune inférence dans les routes."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from backend.app.auth import Database
from backend.app.emotion_config import enabled
from backend.app.history_routes import EMOTIONS
from backend.app.models import Job, User
from backend.app.services import emotions
from backend.app.services.transcripts import owned_dream
from backend.app.transcript_routes import editor_form
from backend.app.web.routes import BrowserSession, render

router = APIRouter(include_in_schema=False)
WARNING = (
    "Cette suggestion automatique est indicative et peut être incorrecte. "
    "Elle ne constitue ni un diagnostic ni un avis médical. Vous pouvez la modifier."
)
ORIGINS = {
    "manual": "Choix manuel",
    "accepted": "Suggestion acceptée",
    "legacy": "Valeur historique de provenance inconnue",
    "withdrawn": "Choix retiré",
    "unset": "Aucun choix",
}
MESSAGES = {
    "idle": "Aucune demande de suggestion.",
    "queued": "En attente du worker CPU local.",
    "running": "Analyse en cours…",
    "done": "Suggestion terminée, à confirmer ou corriger.",
    "abstention": "Abstention : le modèle ne propose pas d’émotion suffisamment déterminée.",
    "outdated": "Résultat dépassé : le récit ou le choix a changé.",
    "failed": "Erreur : l’analyse n’a pas abouti. Vous pouvez choisir une émotion manuellement.",
}


def state(db, owner, identifier):
    view = emotions.projection(db, owner, identifier)
    dream = owned_dream(db, owner, identifier)
    job = db.scalar(
        select(Job)
        .where(Job.dream_id == identifier, Job.kind == "emotion")
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    status, busy = "idle", False
    if job:
        progress = emotions.job_projection(db, owner, job.id)
        busy = job.status in {"queued", "running"}
        status = "outdated" if progress["stale"] else job.status
        if status == "done" and view["suggestion"] and view["suggestion"]["emotion"] is None:
            status = "abstention"
    return {
        **view,
        "job_id": str(job.id) if job else None,
        "status": status,
        "busy": busy,
        "message": MESSAGES.get(status, MESSAGES["failed"]),
        "enabled": enabled(),
        "ready": bool(dream.transcript),
        "value_label": EMOTIONS.get(view["value"], "Non renseignée"),
        "origin_label": ORIGINS[view["source"]],
    }


def page(request, db, session, identifier, *, error=None, status=200):
    progress = state(db, session.user_id, identifier)
    dream = owned_dream(db, session.user_id, identifier)
    return render(
        request,
        "emotion.html",
        status,
        dream=dream,
        progress=progress,
        user=db.get(User, session.user_id),
        expires_at=session.expires_at.isoformat(),
        labels={k: v for k, v in EMOTIONS.items() if k != "non_renseignee"},
        warning=WARNING,
        error=error,
    )


@router.get("/reves/{dream_id}/emotion")
def emotion_page(dream_id: UUID, request: Request, session: BrowserSession, db: Database):
    return page(request, db, session, dream_id)


@router.get("/reves/{dream_id}/emotion/statut")
def emotion_status(dream_id: UUID, session: BrowserSession, db: Database):
    return state(db, session.user_id, dream_id)


def version(value):
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        raise ValueError
    return int(value)


@router.post("/reves/{dream_id}/emotion/{action}")
async def mutate(
    dream_id: UUID, action: str, request: Request, session: BrowserSession, db: Database
):
    fields_by_action = {
        "choisir": {"emotion"},
        "retirer": set(),
        "accepter": {"suggestion_id"},
        "suggerer": {"text_version"},
    }
    if action not in fields_by_action:
        raise HTTPException(404, "Action introuvable")
    fields = await editor_form(request, fields_by_action[action] | {"csrf", "revision"})
    dream = owned_dream(db, session.user_id, dream_id, lock=True)
    try:
        pair = fields["revision"].split(":")
        if len(pair) != 2:
            raise ValueError
        text_version, revision = (version(part) for part in pair)
        if dream.text_version != text_version:
            raise HTTPException(409, "Récit modifié")
        if action == "suggerer":
            if not enabled():
                return page(
                    request,
                    db,
                    session,
                    dream_id,
                    status=409,
                    error="Moteur expérimental désactivé. Le choix manuel reste disponible.",
                )
            emotions.enqueue(
                db, session.user_id, dream_id, version(fields["text_version"]), revision
            )
        elif action == "accepter":
            emotions.accept(db, session.user_id, dream_id, UUID(fields["suggestion_id"]), revision)
        else:
            value = fields["emotion"] if action == "choisir" else None
            if value is not None and value not in EMOTIONS.keys() - {"non_renseignee"}:
                raise ValueError
            emotions.correct(db, session.user_id, dream_id, value, revision)
    except ValueError:
        db.rollback()
        return page(
            request,
            db,
            session,
            dream_id,
            status=422,
            error="Choisissez une émotion valide et rechargez les versions si nécessaire.",
        )
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        db.rollback()
        return page(
            request,
            db,
            session,
            dream_id,
            status=409,
            error="Le récit, le choix ou le traitement a changé. Vérifiez puis réessayez.",
        )
    return RedirectResponse(f"/reves/{dream_id}/emotion?enregistre=1", status_code=303)
