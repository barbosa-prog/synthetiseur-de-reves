"""Consultation privée seulement ; aucun import, export de rêve ou DELETE public."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import sessionmaker
from starlette.background import BackgroundTask

from backend.app.auth import CurrentUser, Database
from backend.app.schemas import ErrorResponse
from backend.app.services.media import MediaNotFound, MediaService
from backend.app.storage.local import LocalPrivateStorage, StorageError
from backend.app.web.routes import BrowserSession

router = APIRouter(tags=["Médias privés"], responses={
    401: {"model": ErrorResponse, "description": "Authentification requise."},
    404: {"model": ErrorResponse, "description": "Média inaccessible."},
    503: {"model": ErrorResponse, "description": "Stockage indisponible."},
})


def media_service(request: Request, db: Database) -> MediaService:
    """Fabrique différée, configurable et remplaçable sans exposer la racine privée."""
    try:
        storage = getattr(request.app.state, "media_storage", None)
        if storage is None:
            storage = LocalPrivateStorage.from_environment()
        return MediaService(storage, sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    except StorageError:
        raise HTTPException(503, "Stockage indisponible") from None


Service = Annotated[MediaService, Depends(media_service)]


def private_response(service: MediaService, user_id: uuid.UUID, media_id: uuid.UUID):
    """Flux déjà ouvert : aucun chemin absolu ou storage_key dans les en-têtes."""
    try:
        download = service.download(user_id, media_id)
    except MediaNotFound:
        raise HTTPException(404, "Média inaccessible") from None
    except StorageError:
        raise HTTPException(503, "Stockage indisponible") from None
    extensions = {"audio/wav": "wav", "audio/mpeg": "mp3", "image/png": "png",
                  "image/jpeg": "jpg", "image/webp": "webp"}
    extension = extensions.get(download.media_type)
    if extension is None:
        download.stream.close()
        raise HTTPException(404, "Média inaccessible")

    def chunks():
        try:
            while chunk := download.stream.read(65536):
                yield chunk
        finally:
            download.stream.close()

    return StreamingResponse(
        chunks(), media_type=download.media_type,
        headers={"Content-Length": str(download.size), "Cache-Control": "no-store",
                 "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; sandbox",
                 "Content-Disposition": f'attachment; filename="media-{media_id}.{extension}"'},
        background=BackgroundTask(download.stream.close),
    )


@router.get("/api/v1/media/{media_id}/content", response_class=StreamingResponse)
def api_media(media_id: uuid.UUID, user: CurrentUser, service: Service):
    """Bearer obligatoire ; connaître l'UUID ou la clé ne donne aucun droit."""
    return private_response(service, user.id, media_id)


@router.get("/web/media/{media_id}/content", response_class=StreamingResponse,
            include_in_schema=False)
def browser_media(media_id: uuid.UUID, session: BrowserSession, service: Service):
    """Cookie P20 HTTPS ; lecture GET uniquement, aucune mutation nécessitant CSRF."""
    return private_response(service, session.user_id, media_id)
