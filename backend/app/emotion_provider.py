"""Contrat P08 sans moteur IA, réseau, base ou chargement implicite."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.text_rules import normalize_text

Emotion = Literal["heureux", "stressant", "neutre", "triste", "autre"]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class EmotionRequest(Contract):
    """Instantané privé ; révision du choix distincte de la version P06."""

    request_id: UUID
    text: str = Field(repr=False)
    text_version: int = Field(ge=1)
    choice_revision: int = Field(ge=0)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        return normalize_text(value)


class EmotionResult(Contract):
    """Abstention explicite ; aucun score présenté comme probabilité médicale."""

    request_id: UUID
    text_version: int = Field(ge=1)
    choice_revision: int = Field(ge=0)
    emotion: Emotion | None
    abstention_reason: Literal["insufficient_information", "ambiguous"] | None = None
    engine: str = Field(min_length=1, max_length=100)
    model_revision: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def consistent_abstention(self):
        if (self.emotion is None) != (self.abstention_reason is not None):
            raise ValueError("Abstention incohérente")
        return self


class EmotionProvider(Protocol):
    def analyze(self, request: EmotionRequest) -> EmotionResult: ...


class EmotionError(Exception):
    """Code stable, sans texte ni exception privée du fournisseur."""

    def __init__(self, code):
        allowed = {
            "provider_failed",
            "invalid_result",
            "stale_result",
            "choice_conflict",
            "disabled",
            "configuration",
            "model_unavailable",
            "timeout",
            "insufficient_memory",
            "worker_stopped",
            "worker_busy",
        }
        super().__init__(code if code in allowed else "provider_failed")


def analyze(provider: EmotionProvider, request: EmotionRequest) -> EmotionResult:
    """Valide la frontière fournisseur ; aucune publication ou reprise implicite."""
    try:
        raw = provider.analyze(request)
    except EmotionError:
        raise
    except Exception:
        raise EmotionError("provider_failed") from None
    if not isinstance(raw, EmotionResult):
        raise EmotionError("invalid_result")
    try:
        result = EmotionResult.model_validate(raw.model_dump())
    except ValueError:
        raise EmotionError("invalid_result") from None
    if (result.request_id, result.text_version, result.choice_revision) != (
        request.request_id,
        request.text_version,
        request.choice_revision,
    ):
        raise EmotionError("stale_result")
    return result


class LocalMDeberta:
    """Adaptateur CPU interchangeable ; le runner isolé possède le chargement."""

    def __init__(self, runner, configuration):
        self.runner, self.configuration = runner, dict(configuration)

    def analyze(self, request):
        if self.configuration.get("inference_enabled") is not True:
            raise EmotionError("disabled")
        raw = self.runner.run(request, self.configuration)
        try:
            result = EmotionResult.model_validate_json(__import__("json").dumps(raw))
        except (ValueError, TypeError):
            raise EmotionError("invalid_result") from None
        if (
            result.engine != self.configuration["engine"]
            or result.model_revision != self.configuration["model_revision"]
        ):
            raise EmotionError("invalid_result")
        return result
