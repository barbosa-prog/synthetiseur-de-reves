"""Routes disponibles dans le périmètre P01."""

from fastapi import APIRouter

from backend.app.schemas import HealthResponse

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthResponse, tags=["Système"])
def health() -> HealthResponse:
    """Vérifie que le processus API répond, sans dépendance externe.

    Returns:
        État et version du backend.
    """
    return HealthResponse()
