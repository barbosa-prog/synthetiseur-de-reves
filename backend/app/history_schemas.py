"""Contrats P09 : liste privée bornée, aucune référence au stockage physique."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Emotion = Literal["heureux", "stressant", "neutre", "triste", "autre"]
EmotionFilter = Literal["heureux", "stressant", "neutre", "triste", "autre", "non_renseignee"]


class HistoryQuery(BaseModel):
    """Paramètres partagés API/page future ; aucune identité fournie par le client."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=12, ge=1, le=50)
    emotion: EmotionFilter | None = None

    @field_validator("page", "page_size", mode="before")
    @classmethod
    def integer_parameter(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 5:
            return int(value)
        if type(value) is int:
            return value
        raise ValueError("Pagination entière attendue")


class HistoryItem(BaseModel):
    """Extrait du récit courant, jamais de chemin, token ou description IA privée."""

    id: uuid.UUID
    created_at: datetime
    status: str
    emotion: Emotion | None
    text_version: int
    text_updated_at: datetime | None
    has_transcript: bool
    excerpt: str | None


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    page: int
    page_size: int
    emotion: EmotionFilter | None
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool
