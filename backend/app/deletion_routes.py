"""Confirmation de suppression : GET non mutateur, POST avec session et CSRF."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.app.auth import Database
from backend.app.models import User
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.transcripts import owned_dream
from backend.app.transcript_routes import editor_form
from backend.app.web.routes import BrowserSession, render

router = APIRouter(include_in_schema=False)


def confirmation(request, db, session, dream_id, *, error=None, status=200):
    dream = owned_dream(db, session.user_id, dream_id)
    return render(request, "delete_dream.html", status, dream=dream, error=error,
                  user=db.get(User, session.user_id), expires_at=session.expires_at.isoformat())


@router.get("/reves/{dream_id}/supprimer")
def confirm_delete(dream_id: UUID, request: Request, session: BrowserSession, db: Database):
    return confirmation(request, db, session, dream_id)


@router.post("/reves/{dream_id}/supprimer")
async def submit_delete(dream_id: UUID, request: Request, session: BrowserSession, db: Database):
    fields = await editor_form(request, {"csrf", "confirmation"})
    if fields["confirmation"] != "supprimer":
        raise HTTPException(422, "Confirmation explicite requise")
    try:
        delete_dream(db, session.user_id, dream_id)
    except HTTPException as exc:
        if exc.status_code not in {409, 503}:
            raise
        return confirmation(request, db, session, dream_id,
                            error=exc.detail, status=exc.status_code)
    return RedirectResponse("/mes-reves", status_code=303)
