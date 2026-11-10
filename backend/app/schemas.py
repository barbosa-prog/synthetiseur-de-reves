"""Contrats JSON publics du socle API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """État du processus API, sans vérification des futurs services."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["synthetiseur-de-reves-api"] = "synthetiseur-de-reves-api"
    version: str = "0.1.0"


class ErrorDetail(BaseModel):
    """Erreur sans contenu utilisateur ni détail technique interne."""

    code: str = Field(description="Code stable exploitable par le client.")
    message: str = Field(description="Message public en français.")


class ErrorResponse(BaseModel):
    """Enveloppe commune des erreurs HTTP."""

    error: ErrorDetail
