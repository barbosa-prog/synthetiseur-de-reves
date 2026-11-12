"""Export d'un seul rêve : Bearer ou formulaire HTTPS avec session et CSRF."""

from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.app.auth import ActiveSession, CurrentUser, Database
from backend.app.export_contract import ExportError
from backend.app.media_routes import Service
from backend.app.models import User
from backend.app.services.export_zip import DELIVERY_SECONDS, ZipExportService
from backend.app.storage.local import StorageError
from backend.app.transcript_routes import editor_form
from backend.app.web.routes import BrowserSession, render

router = APIRouter(tags=["Exports privés"])
ERRORS = {
    "too_many_media": (413, "Ce rêve contient trop de médias pour un export."),
    "export_too_large": (413, "Cet export dépasse la taille maximale autorisée."),
    "export_busy": (409, "Un export est déjà en cours. Réessayez après sa fin."),
    "export_changed": (409, "Le rêve a changé. Rechargez sa page avant de réessayer."),
    "integrity_error": (409, "Un média est altéré. Aucun export n'a été livré."),
    "export_timeout": (504, "La préparation de l'export a dépassé le délai autorisé."),
    "insufficient_disk": (503, "Espace temporaire insuffisant pour préparer l'export."),
}


class ArchiveResponse(StreamingResponse):
    def __init__(self, archive, session_id):
        self.archive = archive
        super().__init__(archive.chunks(session_id), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="reve-{archive.dream}.zip"',
            "Content-Length": str(archive.path.stat().st_size),
            "Cache-Control": "no-store", "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        })

    async def __call__(self, scope, receive, send):
        try:
            with anyio.fail_after(DELIVERY_SECONDS):
                await super().__call__(scope, receive, send)
        finally:
            # Également exécuté si le client se déconnecte avant le premier bloc.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.archive.close)


def download(service, owner, dream_id, session_id, request):
    try:
        root = getattr(request.app.state, "export_root", None)
        limits = getattr(request.app.state, "export_limits", None)
        archive = ZipExportService(service, root=root, limits=limits).build(owner, dream_id)
        try:
            archive.guard(session_id)
            return ArchiveResponse(archive, session_id)
        except BaseException:
            archive.close()
            raise
    except ExportError as exc:
        status, message = ERRORS.get(str(exc), (503, "Export temporairement indisponible."))
        raise HTTPException(status, message) from None
    except (StorageError, OSError):
        raise HTTPException(503, "Export temporairement indisponible.") from None


@router.get("/api/v1/dreams/{dream_id}/export")
def api_export(dream_id: UUID, request: Request, user: CurrentUser,
               session: ActiveSession, service: Service):
    return download(service, user.id, dream_id, session.id, request)


@router.post("/reves/{dream_id}/export", include_in_schema=False)
async def web_export(dream_id: UUID, request: Request, session: BrowserSession,
                     service: Service, db: Database):
    await editor_form(request, {"csrf"})
    try:
        return await run_in_threadpool(
            download, service, session.user_id, dream_id, session.id, request,
        )
    except HTTPException as exc:
        if exc.status_code in {401, 404}:
            raise
        return render(request, "export_error.html", exc.status_code,
                      dream_id=dream_id, message=exc.detail, user=db.get(User, session.user_id))
