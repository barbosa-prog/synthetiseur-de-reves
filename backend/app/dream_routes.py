"""Accès minimal P03 aux rêves existants, toujours filtré par propriétaire."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from backend.app.auth import CurrentUser, Database
from backend.app.auth_schemas import DreamResponse, DreamUpdate
from backend.app.errors import error_response
from backend.app.history_schemas import HistoryPage, HistoryQuery
from backend.app.models import Dream
from backend.app.schemas import ErrorResponse
from backend.app.services.dream_deletion import delete_dream as delete_owned_dream
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
    if "emotion" in changes:
        if payload.expected_emotion_revision is None:
            return error_response(409, "emotion_revision_required",
                                  "Rechargez le choix émotionnel.")
        from backend.app.emotion_rules import check_revision
        from backend.app.services.emotions import metadata, state_for, translate

        translate(check_revision, state_for(db, dream, metadata(db, dream)),
                  payload.expected_emotion_revision)
    if "transcript" in changes:
        if payload.expected_text_version is None:
            return error_response(409, "text_version_required", "Rechargez la version du récit.")
        try:
            apply_correction(db, dream, changes["transcript"], payload.expected_text_version)
        except TextVersionConflict:
            return error_response(409, "text_version_conflict", "Version plus récente disponible.")
    if "emotion" in changes:
        from backend.app.services.emotions import set_choice

        set_choice(db, dream, changes["emotion"])
    db.commit()
    return dream


@router.delete("/{dream_id}", status_code=204)
def delete_dream(dream_id: uuid.UUID, user: CurrentUser, db: Database) -> Response:
    """Retrait atomique, jobs révoqués et médias programmés pour purge P19."""
    delete_owned_dream(db, user.id, dream_id)
    return Response(status_code=204)
