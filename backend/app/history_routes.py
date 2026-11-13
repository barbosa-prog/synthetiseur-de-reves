"""Pages P09 privées ; consultation uniquement, sans traitement IA."""

import uuid
from datetime import timezone
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from pydantic import field_validator
from sqlalchemy import func, select

from backend.app.auth import Database
from backend.app.history_schemas import HistoryQuery
from backend.app.models import Job, Media, User
from backend.app.services.history import list_dreams
from backend.app.services.image_execution import current_image
from backend.app.services.transcripts import owned_dream
from backend.app.web.routes import BrowserSession, render

router = APIRouter(include_in_schema=False)
EMOTIONS = {"heureux": "Heureux", "stressant": "Stressant", "neutre": "Neutre",
            "triste": "Triste", "autre": "Autre", "non_renseignee": "Non renseignée"}
STATES = {"draft": "Brouillon", "processing": "Traitement en cours",
          "transcribing": "Transcription en cours", "transcribed": "Transcrit",
          "correcting": "Correction", "generating": "Génération en cours",
          "ready": "Prêt", "error": "Erreur"}


class WebHistoryQuery(HistoryQuery):
    """12 éléments fixes ; l'option HTML Toutes transmet une valeur vide."""

    page_size: Literal[12] = 12

    @field_validator("emotion", mode="before")
    @classmethod
    def all_emotions(cls, value):
        return None if value == "" else value


def page_url(page, emotion):
    params = {"page": page}
    if emotion is not None:
        params["emotion"] = emotion
    return "/mes-reves?"+urlencode(params)


def utc_date(value):
    """Affichage explicite UTC, indépendant du fuseau de la connexion PostgreSQL."""
    return value.astimezone(timezone.utc)


@router.get("/mes-reves")
def history_page(request: Request, session: BrowserSession, db: Database,
                 query: Annotated[WebHistoryQuery, Query()]):
    history = list_dreams(db, session.user_id, query)
    previous = page_url(query.page-1, query.emotion) if history.has_previous else None
    return render(request, "history.html", user=db.get(User, session.user_id),
                  expires_at=session.expires_at.isoformat(), history=history,
                  emotions=EMOTIONS, states=STATES,
                  utc_date=utc_date,
                  previous_url=previous,
                  next_url=page_url(query.page+1, query.emotion) if history.has_next else None)


@router.get("/reves/{dream_id}")
def dream_detail(dream_id: uuid.UUID, request: Request, session: BrowserSession, db: Database):
    dream = owned_dream(db, session.user_id, dream_id, lock=True)
    audio = db.scalar(select(Media.id).where(
        Media.dream_id == dream_id, Media.kind == "audio", Media.storage_state == "ready",
        Media.audio_source.is_not(None),
        (Media.expires_at.is_(None) | (Media.expires_at > func.now())),
    ).limit(1))
    image = current_image(db, session.user_id, dream_id)
    from backend.app.services.job_tracking import project
    summary = []
    for kind, label, stage in [("stt", "Transcription", "transcription"),
                                ("image", "Image", "image"), ("emotion", "Émotion", "emotion")]:
        job = db.scalar(select(Job).where(Job.dream_id == dream_id, Job.kind == kind)
                        .order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
        if job:
            summary.append(dict(label=label, href=f"/reves/{dream_id}/{stage}",
                                tracking=project(db, session.user_id, job)))
    return render(request, "dream_detail.html", dream=dream, audio=audio,
                  job_summary=summary,
                  image_url=f"/web/media/{image}/content" if image else None,
                  user=db.get(User, session.user_id), expires_at=session.expires_at.isoformat(),
                  emotions=EMOTIONS, states=STATES, utc_date=utc_date)
