"""Projection P11 en lecture seule et actions explicites sur les services existants."""

from contextlib import nullcontext

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from backend.app import job_rules as rules
from backend.app.emotion_config import enabled
from backend.app.emotion_config import parameters as emotion_parameters
from backend.app.job_config import identity, image_parameters, stt_parameters
from backend.app.models import Dream, DreamEmotion, ImageDescription, ImageGeneration, Job
from backend.app.services import job_lifecycle as lifecycle
from backend.app.stt_provider import STTError

LABELS = {"queued": "En attente", "running": "En cours", "done": "Terminé", "failed": "Échec"}
MESSAGES = {"queued": "En attente du worker local.", "running": "Traitement en cours…",
            "done": "Traitement terminé.", "failed": "Le traitement a échoué.",
            "timeout": "Le délai du traitement est dépassé. Aucun nouvel essai automatique.",
            "queue_timeout": "Le délai d’attente est dépassé. Aucun traitement relancé.",
            "safety_blocked": "Le filtre de sécurité a refusé la sortie. Relance interdite.",
            "interrupted": "Le traitement a été interrompu. Aucune relance automatique.",
            "worker_stopped": "Le traitement a été arrêté.",
            "insufficient_memory": "Mémoire insuffisante pour effectuer le traitement.",
            "configuration": "La configuration locale doit être vérifiée."}


def safe_error(code):
    return (code if code is None or code in rules.RETRYABLE | rules.NON_RETRYABLE
            else "unknown_error")


class RetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmed: bool
    expected_text_version: int = Field(ge=0, le=2147483646)
    expected_retry_count: int = Field(ge=0, le=2)
    expected_description_version: int | None = Field(default=None, ge=1, le=2147483646)
    expected_choice_revision: int | None = Field(default=None, ge=0, le=2147483646)


def owned_job(db, owner, identifier, kind):
    job = db.scalar(select(Job).join(Dream).where(Job.id == identifier, Job.kind == kind,
        Dream.user_id == owner, Dream.status != "deleted")
        .execution_options(populate_existing=True))
    if job is None:
        raise HTTPException(404, "Traitement inaccessible")
    return job


def parameters(db, job):
    if job.kind == "stt":
        return stt_parameters()
    if job.kind == "image":
        snapshot = db.get(ImageGeneration, job.id)
        if snapshot is None:
            raise ValueError("configuration")
        return image_parameters(snapshot.parameters["seed"])
    return emotion_parameters()


def project(db, owner, job):
    """Aucune écriture, récupération, réservation, empreinte privée ou jeton exposé."""
    job = owned_job(db, owner, job.id, job.kind)
    dream = db.get(Dream, job.dream_id, populate_existing=True)
    description = db.get(ImageDescription, dream.id) if job.kind == "image" else None
    meta = db.get(DreamEmotion, dream.id) if job.kind == "emotion" else None
    result = dict(job_id=str(job.id), technical_state=job.status, state_label=LABELS[job.status],
        state_message=MESSAGES.get(job.error_code, MESSAGES[job.status]),
        cycle_attempts=None, max_attempts=rules.MAX_ATTEMPTS, retry_count=None,
        max_manual_retries=rules.MAX_RETRIES,
        attempts_remaining=0, retries_remaining=0, budget_known=False, retryable=False,
        regeneratable=False, outdated=False, outcome=None, text_version=dream.text_version,
        description_version=description.version if description else None,
        choice_revision=meta.revision if meta else (0 if job.kind == "emotion" else None),
        retry_url=f"/reves/{dream.id}/traitements/{job.kind}/{job.id}/relancer",
        regenerate_url=f"/reves/{dream.id}/traitements/image/{job.id}/regenerer",
        confirmation="")
    if job.expected_text_version is not None and job.expected_text_version != dream.text_version:
        result["outdated"] = True
    if job.kind == "image":
        snapshot = db.get(ImageGeneration, job.id)
        result["outdated"] = result["outdated"] or not (
            snapshot and description and snapshot.user_id == owner
            and snapshot.text_version == dream.text_version == description.text_version
            and snapshot.transcript == dream.transcript
            and snapshot.description_version == description.version
            and snapshot.description == description.description)
    if result["outdated"]:
        result["state_message"] = "Résultat dépassé : les entrées ou le choix ont changé."
    if job.cycle_key is None:
        result["state_message"] = "Historique non versionné : relance indisponible."
        return result
    try:
        inputs = lifecycle.read_inputs(job.input_snapshot)
        rows = lifecycle.cycle_rows(db, dream, inputs)
        state = lifecycle.state_for(db, job, rows)
        result.update(budget_known=True, cycle_attempts=state.attempts,
                      retry_count=state.retry_count,
                      attempts_remaining=rules.MAX_ATTEMPTS-state.attempts,
                      retries_remaining=min(rules.MAX_RETRIES-state.retry_count,
                                            rules.MAX_ATTEMPTS-state.attempts),
                      outcome=state.outcome)
        current = lifecycle.inputs_for(db, dream, job.kind, inputs.engine, media_id=job.media_id)
        outdated = result["outdated"] or current.cycle_key != job.cycle_key
        if job.kind == "stt" and job.status == "done":
            output = job.input_snapshot.get("_output", {})
            outdated = not (output.get("text_version") == dream.text_version
                and output.get("text_digest") == rules.content_digest(dream.transcript))
        if job.kind == "emotion" and job.status != "done":
            outdated = outdated or state.choice_revision != (meta.revision if meta else 0)
        outdated = outdated or job.error_code in {"text_conflict", "stale_result"}
        result["outdated"] = outdated
        result["state_message"] = MESSAGES.get(job.error_code, MESSAGES[job.status])
        if outdated:
            result["state_message"] = "Résultat dépassé : les entrées ou le choix ont changé."
        elif state.outcome == "abstention":
            result["state_message"] = "Abstention — aucune émotion proposée."
        configured = identity(parameters(db, job)) == inputs.engine
        available = job.kind != "emotion" or enabled()
        latest = bool(rows and rows[-1].id == job.id)
        if not outdated and configured and available and latest:
            try:
                rules.retry(state, db.scalar(select(func.clock_timestamp())), inputs=current,
                            choice_revision=meta.revision if meta else None, explicit=True)
                result["retryable"] = True
            except rules.JobRuleError:
                pass
            active = db.scalar(select(Job.id).where(Job.dream_id == dream.id,
                Job.kind == job.kind, Job.status.in_(["queued", "running"])).limit(1))
            result["regeneratable"] = bool(job.kind == "image" and job.status == "done"
                and result["attempts_remaining"] > 0 and active is None)
        result["confirmation"] = ":".join(str(value) for value in (
            dream.text_version, result["description_version"] or 0,
            result["choice_revision"] or 0, state.retry_count))
    except (rules.JobRuleError, ValidationError, HTTPException, STTError,
            ValueError, KeyError, TypeError):
        # Métadonnées incomplètes ou audio retiré : aucun droit d'action supposé.
        result.update(retryable=False, regeneratable=False)
    return result


def mutate(db, owner, identifier, kind, payload, *, regenerate=False, media_service=None):
    """Verrous du service P11, puis validation optimiste avant son action atomique."""
    owned_job(db, owner, identifier, kind)
    try:
        lifecycle.bounded(db)
        job, dream = lifecycle.lock_job(db, owner, identifier)
        progress = project(db, owner, job)
        if (payload.confirmed is not True
                or payload.expected_text_version != dream.text_version
                or payload.expected_retry_count != progress["retry_count"]
                or (kind == "image" and payload.expected_description_version
                    != progress["description_version"])
                or (kind == "emotion" and payload.expected_choice_revision
                    != progress["choice_revision"])):
            raise HTTPException(409,
                                "Confirmation, versions ou budget modifiés. Rechargez la page.")
        if not progress["regeneratable" if regenerate else "retryable"]:
            raise HTTPException(409, "Cette action n’est pas autorisée pour ce traitement.")
        approved = parameters(db, job)
        if regenerate:
            if kind != "image":
                raise HTTPException(404, "Action introuvable")
            return lifecycle.create(lambda: nullcontext(db), owner, dream.id, "image",
                engine=identity(approved), parameters=approved, text_version=dream.text_version,
                description_version=progress["description_version"], explicit=True,
                new_image=True, media_service=media_service)
        return lifecycle.retry_job(lambda: nullcontext(db), owner, identifier,
                                   engine=identity(approved), explicit=True)
    except (rules.JobRuleError, ValidationError, HTTPException, SQLAlchemyError) as exc:
        db.rollback()
        raise lifecycle.translate_error(exc) from None
