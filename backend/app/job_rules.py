"""Contrat P11 pur, non raccordé : ni SQL, worker, réseau, horloge ou fichier."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["stt", "image", "emotion"]
Status = Literal["queued", "running", "done", "failed"]
MAX_ATTEMPTS = 3
MAX_RETRIES = 2
TRANSITIONS = {
    "queued": frozenset({"running", "failed"}),
    "running": frozenset({"done", "failed"}),
    "failed": frozenset({"queued"}),
    "done": frozenset(),
}
RETRYABLE = frozenset({
    "timeout", "interrupted", "worker_stopped", "worker_busy", "queue_timeout",
    "insufficient_memory", "memory_unknown", "model_unavailable", "provider_unavailable",
    "worker_unavailable", "provider_failed", "network_error", "rate_limited",
})
NON_RETRYABLE = frozenset({
    "safety_blocked", "cancelled", "dream_deleted", "text_conflict", "stale_result",
    "media_unavailable", "invalid_text", "invalid_image", "invalid_result",
    "configuration", "disabled", "outcome_unknown", "unknown_error",
})


class JobRuleError(Exception):
    """Code constant, sans entrée personnelle ou exception fournisseur."""


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class EngineIdentity(Contract):
    engine: str = Field(min_length=1, max_length=100)
    model_revision: str = Field(min_length=1, max_length=100)
    policy_revision: str = Field(min_length=1, max_length=100)
    settings_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Inputs(Contract):
    """Identité INTERNE : configuration serveur et texte déjà validés par P04/P06/P07."""

    owner_id: UUID = Field(repr=False)
    dream_id: UUID = Field(repr=False)
    kind: Kind
    text_version: int = Field(ge=0)
    engine: EngineIdentity = Field(repr=False)
    media_id: UUID | None = Field(default=None, repr=False)
    media_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)
    text_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)
    description_version: int | None = Field(default=None, ge=1)
    description_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)

    @model_validator(mode="after")
    def coherent(self):
        if self.kind == "stt":
            valid = (self.media_id is not None and self.media_sha256 is not None
                     and self.text_digest is None and self.description_version is None
                     and self.description_digest is None)
        else:
            valid = (self.text_version >= 1 and self.text_digest is not None
                     and self.media_id is None and self.media_sha256 is None)
            if self.kind == "image":
                valid = valid and self.description_version is not None
                valid = valid and self.description_digest is not None
            else:
                valid = (valid and self.description_version is None
                         and self.description_digest is None)
        if not valid:
            raise ValueError("Identité de traitement incohérente")
        return self

    @property
    def cycle_key(self):
        # Une copie du même audio sous un nouvel UUID ne recrée pas un budget.
        payload = json.dumps(self.model_dump(mode="json", exclude={"media_id"}), sort_keys=True,
                             separators=(",", ":"))
        return digest("p11-input-v1:" + payload)


def content_digest(text, *, limit=20000):
    # Aucune traduction/normalisation destructive : fournir le texte canonique sauvegardé.
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        raise JobRuleError("invalid_input")
    return digest(text)


class Policy(Contract):
    queued_seconds: int = Field(default=1800, ge=60, le=86400)
    stt_seconds: int = Field(default=600, ge=30, le=1800)
    image_seconds: int = Field(default=120, ge=30, le=600)
    emotion_seconds: int = Field(default=120, ge=30, le=600)
    lease_margin_seconds: int = Field(default=120, ge=60, le=300)
    recovery_interval_seconds: int = Field(default=5, ge=1, le=60)

    def execution_seconds(self, kind: Kind):
        return getattr(self, f"{kind}_seconds")


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise JobRuleError("invalid_time")


class JobState(Contract):
    """Un cycle logique ; les compteurs sont agrégés si plusieurs lignes historiques."""

    inputs: Inputs = Field(repr=False)
    status: Status = "queued"
    attempts: int = Field(default=0, ge=0, le=MAX_ATTEMPTS)
    retry_count: int = Field(default=0, ge=0, le=MAX_RETRIES)
    queued_at: datetime
    lease_until: datetime | None = None
    claim_token: UUID | None = Field(default=None, repr=False)
    choice_revision: int | None = Field(default=None, ge=0, repr=False)
    error_code: str | None = None
    outcome: Literal["result", "abstention"] | None = None
    stale: bool = False

    @model_validator(mode="after")
    def coherent(self):
        aware(self.queued_at)
        if self.lease_until is not None:
            aware(self.lease_until)
        if (self.inputs.kind == "emotion") != (self.choice_revision is not None):
            raise ValueError("Contexte émotionnel incohérent")
        if self.status == "running":
            if (self.attempts < 1 or self.claim_token is None or self.lease_until is None
                    or self.lease_until <= self.queued_at):
                raise ValueError("Réservation incohérente")
        elif self.claim_token is not None or self.lease_until is not None:
            raise ValueError("Réservation hors exécution")
        if (self.status == "failed") != (self.error_code is not None):
            raise ValueError("Erreur et état incohérents")
        if self.error_code and self.error_code not in RETRYABLE | NON_RETRYABLE:
            raise ValueError("Code non public")
        if (self.status == "done") != (self.outcome is not None):
            raise ValueError("Résultat et état incohérents")
        if self.outcome == "abstention" and self.inputs.kind != "emotion":
            raise ValueError("Abstention hors émotion")
        if self.status == "queued" and self.attempts >= MAX_ATTEMPTS:
            raise ValueError("Budget épuisé en attente")
        return self


def _move(state, status, **changes):
    if status not in TRANSITIONS[state.status]:
        raise JobRuleError("invalid_transition")
    return JobState.model_validate({**state.model_dump(), "status": status, **changes})


def current(state, inputs, available, choice_revision):
    if available is not True:
        raise JobRuleError("dream_unavailable")
    if state.inputs.kind == "emotion" and type(choice_revision) is not int:
        raise JobRuleError("stale_result")
    if (state.stale or state.inputs.cycle_key != inputs.cycle_key
            or state.choice_revision != choice_revision):
        raise JobRuleError("stale_result")


def request_job(inputs, now, *, explicit=False, available=True, previous=None,
                choice_revision=None):
    """previous = cycle correspondant, recherché dans TOUT l'historique par le futur service."""
    aware(now)
    if available is not True:
        raise JobRuleError("dream_unavailable")
    if explicit is not True:
        raise JobRuleError("explicit_action_required")
    if previous is not None:
        if previous.inputs.cycle_key != inputs.cycle_key:
            raise JobRuleError("wrong_cycle")
        if previous.choice_revision != choice_revision:
            raise JobRuleError("context_changed")
        if previous.status == "failed":
            raise JobRuleError("retry_required")
        return previous  # Double clic/succès déjà existant : aucun nouveau budget.
    return JobState(inputs=inputs, queued_at=now, choice_revision=choice_revision)


def reserve(state, now, token, *, inputs, available=True, choice_revision=None, policy=Policy()):
    aware(now)
    current(state, inputs, available, choice_revision)
    if state.status != "queued":
        raise JobRuleError("invalid_transition")
    if now < state.queued_at:
        raise JobRuleError("invalid_time")
    if now >= state.queued_at + timedelta(seconds=policy.queued_seconds):
        raise JobRuleError("queue_timeout")
    return _move(state, "running", attempts=state.attempts + 1, claim_token=token,
                lease_until=now + timedelta(seconds=(policy.execution_seconds(state.inputs.kind)
                                                    + policy.lease_margin_seconds)))


def failure(state, code, *, stale=False):
    valid = isinstance(code, str) and code in RETRYABLE | NON_RETRYABLE
    safe = code if valid else "unknown_error"
    return _move(state, "failed", error_code=safe, claim_token=None, lease_until=None,
                outcome=None, stale=state.stale or stale)


def finish(state, now, token, *, inputs, available=True, choice_revision=None,
           error=None, abstention=False):
    aware(now)
    if now < state.queued_at:
        raise JobRuleError("invalid_time")
    if state.status != "running" or token != state.claim_token:
        raise JobRuleError("reservation_lost")
    if now >= state.lease_until:
        raise JobRuleError("lease_expired")
    if available is not True:
        return failure(state, "dream_deleted")
    try:
        current(state, inputs, available, choice_revision)
    except JobRuleError:
        return failure(state, "stale_result", stale=True)
    if error is not None:
        return failure(state, error)
    return _move(state, "done", claim_token=None, lease_until=None,
                outcome="abstention" if abstention else "result")


def retry(state, now, *, inputs, explicit=False, available=True, choice_revision=None):
    aware(now)
    if explicit is not True:
        raise JobRuleError("explicit_action_required")
    current(state, inputs, available, choice_revision)
    if state.status != "failed":
        raise JobRuleError("invalid_transition")
    if state.error_code not in RETRYABLE:
        raise JobRuleError("not_retryable")
    if state.attempts >= MAX_ATTEMPTS or state.retry_count >= MAX_RETRIES:
        raise JobRuleError("budget_exhausted")
    if now < state.queued_at:
        raise JobRuleError("invalid_time")
    return _move(state, "queued", retry_count=state.retry_count + 1, queued_at=now,
                error_code=None, outcome=None)


def recover(state, now, *, inputs, available=True, choice_revision=None, policy=Policy()):
    """Aucune horloge réelle ni relance. Toute récupération est idempotente."""
    aware(now)
    if state.status in {"done", "failed"}:
        return state
    if available is not True:
        return failure(state, "dream_deleted")
    try:
        current(state, inputs, available, choice_revision)
    except JobRuleError:
        return failure(state, "stale_result", stale=True)
    if now < state.queued_at:
        raise JobRuleError("invalid_time")
    if (state.status == "queued"
            and now >= state.queued_at + timedelta(seconds=policy.queued_seconds)):
        return failure(state, "queue_timeout")
    if state.status == "running" and now >= state.lease_until:
        return failure(state, "interrupted")
    return state


def refresh_emotion_context(state, now, *, inputs, choice_revision, explicit=False, available=True):
    """Nouvelle demande P08 explicite, ancien job conservé ; budget du cycle conservé."""
    aware(now)
    if available is not True:
        raise JobRuleError("dream_unavailable")
    if explicit is not True:
        raise JobRuleError("explicit_action_required")
    if (state.inputs.kind != "emotion" or inputs.cycle_key != state.inputs.cycle_key
            or type(choice_revision) is not int or choice_revision <= state.choice_revision):
        raise JobRuleError("stale_result")
    if state.status not in {"done", "failed"}:
        raise JobRuleError("active_conflict")
    if (state.status == "failed"
            and state.error_code not in RETRYABLE | {"stale_result", "cancelled"}):
        raise JobRuleError("not_retryable")
    if state.attempts >= MAX_ATTEMPTS or state.retry_count >= MAX_RETRIES:
        raise JobRuleError("budget_exhausted")
    if now < state.queued_at:
        raise JobRuleError("invalid_time")
    return JobState(inputs=inputs, queued_at=now, attempts=state.attempts,
                    retry_count=state.retry_count + 1, choice_revision=choice_revision)


def public_progress(state, *, inputs, available=True, choice_revision=None):
    """Nouvelle projection proposée ; aucun changement des projections historiques."""
    scope = (state.inputs.owner_id, state.inputs.dream_id, state.inputs.kind)
    if available is not True or scope != (inputs.owner_id, inputs.dream_id, inputs.kind):
        raise JobRuleError("dream_unavailable")
    stale = (state.stale or inputs.cycle_key != state.inputs.cycle_key
             or state.choice_revision != choice_revision)
    return dict(state=state.status, attempts=state.attempts, max_attempts=MAX_ATTEMPTS,
                retry_count=state.retry_count, max_retries=MAX_RETRIES,
                error_code=state.error_code, stale=stale, outcome=state.outcome,
                retryable=(not stale and state.status == "failed" and state.error_code in RETRYABLE
                           and state.attempts < MAX_ATTEMPTS and state.retry_count < MAX_RETRIES))
