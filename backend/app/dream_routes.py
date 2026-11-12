"""Accès minimal P03 aux rêves existants, toujours filtré par propriétaire."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from backend.app.auth import CurrentUser, Database
from backend.app.auth_schemas import DreamResponse, DreamUpdate
from backend.app.errors import error_response
from backend.app.history_schemas import HistoryPage, HistoryQuery
from backend.app.models import Dream
from backend.app.schemas import ErrorResponse
from backend.app.services.history import list_dreams
from backend.app.services.transcripts import TextVersionConflict, apply_correction
from backend.app.services.transcripts import owned_dream as find_owned_dream

router = APIRouter(prefix="/api/v1/dreams", tags=["Rêves privés"], responses={
    401: {"model": ErrorResponse, "description": "Authentification requise."},
    503: {"model": ErrorResponse, "description": "Base indisponible."},
})


def owned_dream(db, user, dream_id: uuid.UUID) -> Dream:
    """Même 404 pour un UUID absent, supprimé ou appartenant à un autre compte."""
    return find_owned_dream(db, user.id, dream_id, lock=True)


@router.get("", response_model=HistoryPage)
def history(user: CurrentUser, db: Database, query: Annotated[HistoryQuery, Query()]):
    """Historique Bearer, sans lecture des fichiers privés ni lancement IA."""
    return list_dreams(db, user.id, query)


@router.get("/{dream_id}", response_model=DreamResponse)
def read_dream(dream_id: uuid.UUID, user: CurrentUser, db: Database) -> Dream:
    """Lit uniquement un rêve du compte connecté."""
    return owned_dream(db, user, dream_id)


@router.patch("/{dream_id}", response_model=DreamResponse)
def update_dream(dream_id: uuid.UUID, payload: DreamUpdate,
                 user: CurrentUser, db: Database) -> Dream:
    """Mutation minimale ; user_id, statut et clés de stockage ne sont pas acceptés."""
    dream = owned_dream(db, user, dream_id)
    changes = payload.model_dump(exclude_unset=True)
    if "transcript" in changes:
        if payload.expected_text_version is None:
            return error_response(409, "text_version_required", "Rechargez la version du récit.")
        try:
            apply_correction(db, dream, changes["transcript"], payload.expected_text_version)
        except TextVersionConflict:
            return error_response(409, "text_version_conflict", "Version plus récente disponible.")
    if "emotion" in changes:
        dream.emotion = changes["emotion"]
    db.commit()
    return dream


@router.delete("/{dream_id}", status_code=204)
def delete_dream(dream_id: uuid.UUID, user: CurrentUser, db: Database) -> Response:
    """Rend le rêve inaccessible ; purge physique différée à P10/P19."""
    dream = owned_dream(db, user, dream_id)
    dream.status = "deleted"
    dream.deleted_at = db.scalar(select(func.clock_timestamp()))
    db.commit()
    return Response(status_code=204)
