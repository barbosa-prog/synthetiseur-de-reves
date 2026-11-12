"""Contrat image sans import IA, réseau ou chargement implicite dans FastAPI."""

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Limite contractuelle identique à P19, sans importer son service/sa configuration DB.
MAX_IMAGE = 8 * 1024 * 1024


class ImageError(Exception):
    """Erreur à code stable, sans description privée ni exception du moteur."""

    def __init__(self, code: str):
        allowed = {"configuration", "model_unavailable", "worker_unavailable", "timeout",
                   "provider_failed", "safety_blocked", "invalid_image", "text_conflict",
                   "insufficient_memory", "worker_stopped"}
        super().__init__(code if code in allowed else "provider_failed")


class ImageRequest(BaseModel):
    """Description indépendante, saisie par l'utilisateur ; aucune traduction implicite."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    description: str = Field(min_length=1, max_length=500, repr=False)
    text_version: int = Field(ge=1)
    description_version: int = Field(ge=1)
    seed: int = Field(default=42, ge=0, le=2**32-1)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Description visuelle invalide")
        return value


@dataclass(frozen=True)
class ImageResult:
    """PNG en mémoire, à publier par le service privé après contrôle transactionnel."""

    png: bytes = field(repr=False)
    text_version: int
    description_version: int


class ImageProvider(Protocol):
    """Moteur interchangeable ; aucune URL publique comme résultat."""

    def generate(self, request: ImageRequest) -> ImageResult: ...


@dataclass(frozen=True)
class SD15Config:
    """Paramètres locaux qualifiés ; aucun secret ni téléchargement."""

    model_path: Path = field(repr=False)
    steps: int = 20
    width: int = 512
    height: int = 512
    timeout_seconds: int = 120

    def __post_init__(self):
        if (not self.model_path.is_absolute() or self.steps != 20
                or (self.width, self.height) != (512, 512) or self.timeout_seconds != 120):
            raise ImageError("configuration")


class IsolatedImageRunner(Protocol):
    """Frontière du futur processus GPU surveillé, distinct du worker STT."""

    def run(self, config: SD15Config, request: ImageRequest) -> tuple[bytes, bool]:
        """Retourne PNG et statut de blocage ; timeout/ressources garantis par le runner."""
        ...


def validate_result(result: ImageResult, request: ImageRequest) -> ImageResult:
    """Refuse un moteur incohérent, une ancienne version ou un faux PNG."""
    if not isinstance(result, ImageResult):
        raise ImageError("invalid_image")
    if (result.text_version != request.text_version
            or result.description_version != request.description_version):
        raise ImageError("text_conflict")
    if not isinstance(result.png, bytes) or not 0 < len(result.png) <= MAX_IMAGE:
        raise ImageError("invalid_image")
    try:
        with Image.open(io.BytesIO(result.png)) as image:
            if image.format != "PNG" or image.size != (512, 512):
                raise ImageError("invalid_image")
            image.verify()
    except ImageError:
        raise
    except Exception:
        raise ImageError("invalid_image") from None
    return result


class LocalStableDiffusion15:
    """Adaptateur local : exécution déléguée explicitement au futur runner isolé.

    Sans runner injecté, échoue fermé ; ne charge jamais de modèle dans FastAPI.
    Le runner réel et ses protections système seront raccordés lors d'une phase suivante.
    """

    def __init__(self, config: SD15Config, runner: IsolatedImageRunner | None = None):
        self.config, self.runner = config, runner

    def generate(self, request: ImageRequest) -> ImageResult:
        if self.runner is None:
            raise ImageError("worker_unavailable")
        required = ("unet/diffusion_pytorch_model.fp16.safetensors",
                    "vae/diffusion_pytorch_model.fp16.safetensors",
                    "text_encoder/model.fp16.safetensors", "safety_checker/model.fp16.safetensors",
                    "model_index.json", "feature_extractor/preprocessor_config.json")
        if not all((self.config.model_path / name).is_file() for name in required):
            raise ImageError("model_unavailable")
        try:
            png, blocked = self.runner.run(self.config, request)
            if type(blocked) is not bool:
                raise ImageError("provider_failed")
            if blocked:
                raise ImageError("safety_blocked")
            return validate_result(ImageResult(png, request.text_version,
                                               request.description_version), request)
        except ImageError:
            raise
        except TimeoutError:
            raise ImageError("timeout") from None
        except Exception:
            raise ImageError("provider_failed") from None
