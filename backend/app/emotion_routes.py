"""API P08 Bearer ; aucun cookie accepté, aucun moteur chargé."""

from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.auth import CurrentUser, Database
from backend.app.emotion_provider import Emotion
from backend.app.services import emotions

router = APIRouter(prefix="/api/v1", tags=["Émotion expérimentale"])


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)


class Choice(Revision):
    emotion: Emotion | None


class Suggestion(Revision):
    expected_text_version: int = Field(ge=1, strict=True)


class Acceptance(Revision):
    suggestion_id: UUID


@router.get("/dreams/{dream_id}/emotion")
def read(dream_id: UUID, user: CurrentUser, db: Database):
    return emotions.projection(db, user.id, dream_id)


@router.put("/dreams/{dream_id}/emotion")
def correct(dream_id: UUID, payload: Choice, user: CurrentUser, db: Database):
    return emotions.correct(db, user.id, dream_id, payload.emotion, payload.expected_revision)


@router.post("/dreams/{dream_id}/emotion/suggestions", status_code=202)
def request(dream_id: UUID, payload: Suggestion, user: CurrentUser, db: Database):
    return emotions.enqueue(
        db, user.id, dream_id, payload.expected_text_version, payload.expected_revision
    )


@router.post("/dreams/{dream_id}/emotion/accept")
def accept(dream_id: UUID, payload: Acceptance, user: CurrentUser, db: Database):
    return emotions.accept(db, user.id, dream_id, payload.suggestion_id, payload.expected_revision)


@router.get("/emotion-jobs/{job_id}")
def status(job_id: UUID, user: CurrentUser, db: Database):
    return emotions.job_projection(db, user.id, job_id)


@router.delete("/emotion-jobs/{job_id}", status_code=204)
def cancel(job_id: UUID, user: CurrentUser, db: Database):
    emotions.cancel(db, user.id, job_id)
    return Response(status_code=204)
