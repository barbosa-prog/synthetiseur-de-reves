"""Schémas publics P03 ; secrets masqués dans les représentations Python."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
)

from backend.app.text_rules import normalize_text


class Credentials(BaseModel):
    """Identifiants JSON ; aucune utilisation en paramètres d'URL."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=15, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalise la casse conformément à la politique de compte locale."""
        return value.lower()


class UserResponse(BaseModel):
    """Projection sans mot de passe ni hachage."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str


class LoginResponse(BaseModel):
    """Jeton communiqué uniquement à la connexion et sous Cache-Control no-store."""

    access_token: SecretStr
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime

    @field_serializer("access_token", when_used="json")
    def serialize_token(self, value: SecretStr) -> str:
        """Divulgue le jeton uniquement dans la réponse JSON attendue du login."""
        return value.get_secret_value()


class SessionResponse(BaseModel):
    """Identité et expiration, sans renvoyer le jeton."""

    user: UserResponse
    expires_at: datetime


class DreamResponse(BaseModel):
    """Projection privée minimale, indépendante de l'historique P09."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    transcript: str | None
    emotion: str | None
    status: str
    text_version: int
    text_updated_at: datetime | None


class DreamUpdate(BaseModel):
    """Mutation minimale pour vérifier P03 ; aucun propriétaire modifiable."""

    model_config = ConfigDict(extra="forbid")
    transcript: str | None = Field(default=None, max_length=20000)
    emotion: Literal["heureux", "stressant", "neutre", "triste", "autre"] | None = None
    expected_text_version: int | None = Field(default=None, ge=0, le=2147483646, strict=True)

    @field_validator("transcript", mode="before")
    @classmethod
    def nonblank_text(cls, value: str | None) -> str:
        """Refuse l'effacement d'un récit par une correction vide."""
        return normalize_text(value)
