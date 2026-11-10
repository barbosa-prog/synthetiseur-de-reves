"""Accès minimal P03 aux rêves existants, toujours filtré par propriétaire."""

import uuid

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from backend.app.auth import CurrentUser, Database
from backend.app.auth_schemas import DreamResponse, DreamUpdate
from backend.app.models import Dream
from backend.app.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/dreams", tags=["Rêves privés"], responses={
    401: {"model": ErrorResponse, "description": "Authentification requise."},
    503: {"model": ErrorResponse, "description": "Base indisponible."},
})


def owned_dream(db, user, dream_id: uuid.UUID) -> Dream:
    """Même 404 pour un UUID absent, supprimé ou appartenant à un autre compte."""
    dream = db.scalar(select(Dream).where(
        Dream.id == dream_id, Dream.user_id == user.id, Dream.status != "deleted",
    ).with_for_update())
    if dream is None:
        raise HTTPException(404, "Ressource introuvable")
    return dream


@router.get("/{dream_id}", response_model=DreamResponse)
def read_dream(dream_id: uuid.UUID, user: CurrentUser, db: Database) -> Dream:
    """Lit uniquement un rêve du compte connecté."""
    return owned_dream(db, user, dream_id)


@router.patch("/{dream_id}", response_model=DreamResponse)
def update_dream(dream_id: uuid.UUID, payload: DreamUpdate,
                 user: CurrentUser, db: Database) -> Dream:
    """Mutation minimale ; user_id, statut et clés de stockage ne sont pas acceptés."""
    dream = owned_dream(db, user, dream_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dream, field, value)
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
