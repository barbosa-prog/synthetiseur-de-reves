"""Corrections privées avec verrou de ligne et contrôle optimiste de la version du texte."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import Dream
from backend.app.text_rules import normalize_text


class TextVersionConflict(Exception):
    """Aucun texte inclus dans l'exception ; seule la version a changé."""


def owned_dream(db: Session, user_id: uuid.UUID, dream_id: uuid.UUID, *, lock=False) -> Dream:
    """Même 404 pour inconnu, supprimé et autre propriétaire."""
    query = select(Dream).where(
        Dream.id == dream_id, Dream.user_id == user_id, Dream.status != "deleted",
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    dream = db.scalar(query)
    if dream is None:
        raise HTTPException(404, "Ressource introuvable")
    return dream


def apply_correction(db: Session, dream: Dream, text: str, expected_version: int | None) -> None:
    """À appeler sur un rêve propriétaire verrouillé ; le caller valide sa transaction.

    P05 devra utiliser cette règle avec sa version de départ et ne jamais écraser
    silencieusement une correction. P07 devra capturer puis revérifier la version
    avant de publier son résultat. Aucun job ni génération n'est créé ici.
    """
    normalized = normalize_text(text)
    if expected_version is not None and expected_version != dream.text_version:
        raise TextVersionConflict
    if normalized != dream.transcript:
        from backend.app.services.emotions import invalidate_for_text

        invalidate_for_text(db, dream, dream.text_version+1)
        dream.transcript = normalized
        dream.text_version += 1
        dream.text_updated_at = db.scalar(select(func.clock_timestamp()))
