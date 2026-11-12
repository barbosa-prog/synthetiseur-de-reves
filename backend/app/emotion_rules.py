"""Transitions P08 pures ; suggestions séparées des choix explicites."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend.app.emotion_provider import (
    Contract,
    Emotion,
    EmotionError,
    EmotionRequest,
    EmotionResult,
)


class EmotionState(Contract):
    text_version: int = Field(ge=0)
    revision: int = Field(default=0, ge=0)
    value: Emotion | None = None
    source: Literal["unset", "manual", "accepted", "withdrawn", "legacy"] = "unset"
    selected_text_version: int | None = Field(default=None, ge=0)
    suggestion: EmotionResult | None = None
    active_request: UUID | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.source in {"unset", "withdrawn"}) != (self.value is None):
            raise ValueError("Origine et choix incohérents")
        if self.value is None and self.selected_text_version is not None:
            raise ValueError("Version sans choix")
        if (self.value is not None and self.selected_text_version is None
                and self.source != "legacy"):
            raise ValueError("Choix sans version")
        if (self.selected_text_version is not None
                and self.selected_text_version > self.text_version):
            raise ValueError("Version future")
        if self.suggestion and self.suggestion.text_version != self.text_version:
            raise ValueError("Suggestion périmée")
        return self


def transition(state, **changes):
    """Revalide les invariants ; model_copy seul ne revalide pas les valeurs."""
    return EmotionState.model_validate({**state.model_dump(), **changes})


def check_revision(state, expected_revision):
    if type(expected_revision) is not int or expected_revision != state.revision:
        raise EmotionError("choice_conflict")


def begin_analysis(state: EmotionState, text: str, request_id: UUID,
                   expected_revision: int) -> tuple[EmotionState, EmotionRequest]:
    check_revision(state, expected_revision)
    request = EmotionRequest(request_id=request_id, text=text, text_version=state.text_version,
                             choice_revision=state.revision+1)
    return transition(state, revision=request.choice_revision, active_request=request_id), request


def publish(state: EmotionState, result: EmotionResult) -> EmotionState:
    """À refaire sous verrous PostgreSQL/bail avant toute écriture future."""
    result = EmotionResult.model_validate(result.model_dump())
    if (state.active_request, state.text_version, state.revision) != (
            result.request_id, result.text_version, result.choice_revision):
        raise EmotionError("stale_result")
    changes = dict(suggestion=result, active_request=None, revision=state.revision+1)
    return transition(state, **changes)


def choose(state: EmotionState, emotion: Emotion | None, expected_revision: int) -> EmotionState:
    """Même valeur = acte manuel ; None = retrait protégé, jamais simple absence."""
    check_revision(state, expected_revision)
    return transition(state, value=emotion, source="manual" if emotion is not None else "withdrawn",
                      selected_text_version=state.text_version if emotion is not None else None,
                      active_request=None, revision=state.revision+1)


def accept(state: EmotionState, request_id: UUID, expected_revision: int) -> EmotionState:
    check_revision(state, expected_revision)
    if (not state.suggestion or state.suggestion.request_id != request_id
            or state.suggestion.emotion is None):
        raise EmotionError("stale_result")
    return transition(state, value=state.suggestion.emotion, source="accepted",
                      selected_text_version=state.text_version, active_request=None,
                      revision=state.revision+1)


def text_changed(state: EmotionState, new_version: int) -> EmotionState:
    if type(new_version) is not int or new_version < state.text_version:
        raise EmotionError("stale_result")
    if new_version == state.text_version:
        return state
    changes = dict(text_version=new_version, suggestion=None, active_request=None,
                   revision=state.revision+1)
    return transition(state, **changes)
