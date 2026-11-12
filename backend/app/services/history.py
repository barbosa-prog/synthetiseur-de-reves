"""Lecture P09 : propriétaire imposé par le serveur, pagination et filtre SQL."""

import uuid

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from backend.app.history_schemas import HistoryItem, HistoryPage, HistoryQuery
from backend.app.models import Dream


def list_dreams(db: Session, user_id: uuid.UUID, query: HistoryQuery) -> HistoryPage:
    """Liste les rêves non supprimés sans requérir transcription ou média.

    Args:
        db: Session de lecture de l'application.
        user_id: Identité issue exclusivement de l'authentification serveur.
        query: Paramètres validés, réutilisables par la future page HTML.

    Returns:
        Page bornée d'extraits privés et métadonnées de pagination.
    """
    filters = [Dream.user_id == user_id, Dream.status != "deleted"]
    if query.emotion == "non_renseignee":
        filters.append(Dream.emotion.is_(None))
    elif query.emotion is not None:
        filters.append(Dream.emotion == query.emotion)
    # Une seule instruction : total et page issus du même snapshot PostgreSQL.
    total = select(func.count()).select_from(Dream).where(*filters).cte("history_total")
    page = select(
        Dream.id, Dream.created_at, Dream.status, Dream.emotion, Dream.text_version,
        Dream.text_updated_at, Dream.transcript.is_not(None).label("has_transcript"),
        func.left(Dream.transcript, 200).label("excerpt"),
    ).where(*filters).order_by(Dream.created_at.desc(), Dream.id.desc()).limit(query.page_size)
    page = page.offset((query.page-1)*query.page_size).cte("history_page")
    statement = select(total.c[0].label("total"), *page.c).select_from(
        total.outerjoin(page, true()),
    ).order_by(page.c.created_at.desc(), page.c.id.desc())
    rows = db.execute(statement).mappings().all()
    count = rows[0]["total"]
    items = [HistoryItem(**{key: row[key] for key in HistoryItem.model_fields})
             for row in rows if row["id"] is not None]
    pages = (count+query.page_size-1)//query.page_size
    return HistoryPage(items=items, page=query.page, page_size=query.page_size,
                       emotion=query.emotion, total=count, total_pages=pages,
                       has_next=query.page < pages, has_previous=count > 0 and query.page > 1)
