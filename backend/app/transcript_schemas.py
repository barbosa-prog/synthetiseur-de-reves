"""Contrat P06 : la version attendue est obligatoire sur la route dédiée."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.text_rules import MAX_TEXT_LENGTH, normalize_text


class TranscriptUpdate(BaseModel):
    """Texte brut ; pas d'HTML interprété ou de propriétaire fourni par le client."""

    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(max_length=MAX_TEXT_LENGTH)
    expected_version: int = Field(ge=0, le=2147483646, strict=True)

    @field_validator("transcript", mode="before")
    @classmethod
    def validate_text(cls, value):
        """Applique la même validation aux API et aux formulaires."""
        return normalize_text(value)


class TranscriptResponse(BaseModel):
    """État courant du texte, sans média ni clé privée."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    transcript: str | None
    text_version: int
    text_updated_at: datetime | None
