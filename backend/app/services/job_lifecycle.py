"""P11 interne PostgreSQL ; aucun moteur ni route, stockage P19 explicitement injecté."""

import json
import os
from contextlib import nullcontext
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app import job_rules as rules
from backend.app.models import (
    Dream,
    DreamEmotion,
    EmotionAnalysis,
    ImageDescription,
    ImageGeneration,
    Job,
    Media,
)
from backend.app.services import ai_quota


def bounded(db):
    db.execute(text("SET LOCAL lock_timeout = '3s'"))
    db.execute(text("SET LOCAL statement_timeout = '10s'"))


def translate_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, rules.JobRuleError):
        return HTTPException(409, "Demande, versions ou budget incompatibles.")
    contention = getattr(getattr(exc, "orig", None), "sqlstate", None) in {
        "55P03", "40P01", "40001"}
    return HTTPException(409 if contention else 503,
                         "Traitement temporairement indisponible.",
                         headers={"Retry-After": "1"} if contention else None)


def owned(db, owner, dream_id):
    dream = db.scalar(select(Dream).where(Dream.id == dream_id, Dream.user_id == owner,
        Dream.status != "deleted").with_for_update(nowait=True)
        .execution_options(populate_existing=True))
    if dream is None:
        raise HTTPException(404, "Ressource introuvable")
    return dream


def inputs_for(db, dream, kind, engine, *, media_id=None):
    fields = dict(owner_id=dream.user_id, dream_id=dream.id, kind=kind,
                  text_version=dream.text_version, engine=engine)
    if kind == "stt":
        media = db.scalar(select(Media).where(Media.id == media_id, Media.dream_id == dream.id,
            Media.kind == "audio", Media.storage_state == "ready", Media.audio_source.is_not(None),
            (Media.expires_at.is_(None) | (Media.expires_at > func.clock_timestamp()))))
        if media is None:
            raise HTTPException(404, "Audio inaccessible")
        fields.update(media_id=media.id, media_sha256=media.sha256)
    else:
        fields["text_digest"] = rules.content_digest(dream.transcript)
        if kind == "image":
            description = db.get(ImageDescription, dream.id, populate_existing=True)
            if description is None or description.text_version != dream.text_version:
                raise rules.JobRuleError("stale_result")
            fields.update(description_version=description.version,
                          description_digest=rules.content_digest(description.description,
                                                                  limit=500))
    return rules.Inputs(**fields)


def cycle_rows(db, dream, identity):
    return list(db.scalars(select(Job).where(Job.dream_id == dream.id,
        Job.kind == identity.kind, Job.cycle_key == identity.cycle_key)
        .order_by(Job.created_at, Job.id).execution_options(populate_existing=True)))


def state_for(db, job, rows):
    identity = read_inputs(job.input_snapshot)
    analysis = db.get(EmotionAnalysis, job.id) if job.kind == "emotion" else None
    outcome = ("abstention" if analysis and analysis.result
               and analysis.result.get("emotion") is None else "result")
    return rules.JobState(inputs=identity, status=job.status,
        attempts=sum(j.attempts for j in rows), retry_count=sum(j.retry_count for j in rows),
        queued_at=job.queued_at, claim_token=job.claim_token, lease_until=job.lease_until,
        choice_revision=analysis.choice_revision if analysis else None,
        error_code=(job.error_code if job.error_code in rules.RETRYABLE | rules.NON_RETRYABLE
                    else "unknown_error") if job.status == "failed" else None,
        outcome=outcome if job.status == "done" else None)


def result_valid(db, job, dream, now, media_service=None):
    if job.kind == "stt":
        return bool(dream.transcript and dream.text_version == job.expected_text_version)
    if job.kind == "image":
        media = db.get(Media, job.media_id) if job.media_id else None
        available = bool(media and media.dream_id == dream.id and media.kind == "image"
                    and media.storage_state == "ready"
                    and (media.expires_at is None or media.expires_at > now))
        if not available or media_service is None:
            return False
        from backend.app.services.media import MediaIntegrityError, MediaNotFound
        from backend.app.storage.local import StorageError
        try:
            download = media_service.download(dream.user_id, media.id, strict_integrity=True)
            download.stream.close()
            return True
        except (MediaIntegrityError, MediaNotFound, StorageError, OSError):
            return False
    meta = db.get(DreamEmotion, dream.id)
    analysis = db.get(EmotionAnalysis, job.id)
    return bool(meta and meta.suggestion_id == job.id and analysis and analysis.result)


def guard_legacy_creation(db, dream_id, kind):
    """Pas de retour vers les anciennes créations après activation interne P11."""
    if db.scalar(select(Job.id).where(Job.dream_id == dream_id, Job.kind == kind,
                                     Job.cycle_key.is_not(None)).limit(1)) is not None:
        raise HTTPException(409, "Ce traitement utilise le cycle P11. Rechargez son suivi.")


def create(sessions, owner, dream_id, kind, *, engine, parameters, text_version,
           media_id=None, description_version=None, choice_revision=None,
           explicit=False, new_image=False, media_service=None):
    """Configuration exclusivement serveur, partagée par les demandes existantes."""
    with sessions() as db:
        try:
            bounded(db)
            dream = owned(db, owner, dream_id)
            identity = inputs_for(db, dream, kind, engine, media_id=media_id)
            if identity.text_version != text_version:
                raise rules.JobRuleError("stale_result")
            if kind == "image" and identity.description_version != description_version:
                raise rules.JobRuleError("stale_result")
            if rules.digest(json.dumps(parameters, sort_keys=True, separators=(",", ":"))) != (
                engine.settings_digest
            ):
                raise rules.JobRuleError("configuration")
            # Les historiques sans configuration fiable ne sont jamais réétiquetés P11.
            if db.scalar(select(Job.id).where(Job.dream_id == dream_id, Job.kind == kind,
                Job.cycle_key.is_(None)).limit(1)) is not None:
                raise HTTPException(409, "Historique non versionné : validation nécessaire.")
            if db.scalar(select(Job.id).where(Job.dream_id == dream_id, Job.kind == kind,
                Job.status.in_(["queued", "running"])).limit(1)) is not None:
                raise HTTPException(409, "Un traitement est déjà actif.")
            rows = cycle_rows(db, dream, identity)
            now = db.scalar(select(func.clock_timestamp()))
            meta = db.get(DreamEmotion, dream.id) if kind == "emotion" else None
            if kind == "emotion" and choice_revision != (meta.revision if meta else 0):
                raise rules.JobRuleError("stale_result")
            if explicit is not True:
                raise rules.JobRuleError("explicit_action_required")
            retry_cost = 0
            if kind == "stt":
                # La sortie P05 change la version P06 : comparer la sortie publiée,
                # pas seulement la version d'entrée du cycle précédent.
                successes = db.scalars(select(Job).where(Job.dream_id == dream_id,
                    Job.kind == "stt", Job.status == "done", Job.cycle_key.is_not(None)))
                for completed in successes:
                    old = read_inputs(completed.input_snapshot)
                    output = completed.input_snapshot.get("_output", {})
                    if (old.engine == engine and old.media_sha256 == identity.media_sha256
                            and output.get("text_version") == dream.text_version
                            and output.get("text_digest") == rules.content_digest(
                                dream.transcript)):
                        db.commit()
                        return completed.id
            if rows:
                latest = rows[-1]
                previous = state_for(db, latest, rows)
                if (kind == "emotion" and previous.status == "failed"
                        and previous.choice_revision != meta.revision):
                    refreshed = rules.refresh_emotion_context(previous, now, inputs=identity,
                        choice_revision=meta.revision, explicit=True)
                    retry_cost = refreshed.retry_count - previous.retry_count
                if previous.status == "failed":
                    if retry_cost == 0:
                        raise rules.JobRuleError("retry_required")
                elif kind == "image" and new_image is True:
                    if previous.attempts >= rules.MAX_ATTEMPTS:
                        raise rules.JobRuleError("budget_exhausted")
                    # Pas de budget neuf : 3 exécutions, réussies ou non, pour ces entrées.
                else:
                    if new_image or not result_valid(db, latest, dream, now, media_service):
                        raise rules.JobRuleError("invalid_result")
                    db.commit()
                    return latest.id
            if new_image and kind != "image":
                raise rules.JobRuleError("invalid_input")
            ai_quota.check(db, owner)
            job = Job(dream_id=dream.id, kind=kind, expected_text_version=text_version,
                      media_id=media_id, queued_at=now, retry_count=retry_cost,
                      cycle_key=identity.cycle_key, input_snapshot=identity.model_dump(mode="json"))
            db.add(job)
            db.flush()
            if kind == "image":
                description = db.get(ImageDescription, dream.id)
                db.add(ImageGeneration(job_id=job.id, user_id=owner, transcript=dream.transcript,
                    text_version=text_version, description=description.description,
                    description_version=description_version, parameters=parameters))
            elif kind == "emotion":
                if meta is None:
                    meta = DreamEmotion(dream_id=dream.id,
                                        source="legacy" if dream.emotion else "unset", revision=0)
                    db.add(meta)
                meta.revision += 1
                meta.active_request = job.id
                db.add(EmotionAnalysis(job_id=job.id, user_id=owner, transcript=dream.transcript,
                    text_version=text_version, choice_revision=meta.revision,
                    parameters=parameters))
            db.commit()
            return job.id
        except (SQLAlchemyError, rules.JobRuleError, HTTPException, ValidationError) as exc:
            db.rollback()
            raise translate_error(exc) from None


def lock_job(db, owner, job_id):
    # Lecture d'autorisation avant tout verrou ; même 404 pour supprimé/étranger.
    if db.scalar(select(Job.id).join(Dream).where(Job.id == job_id, Dream.user_id == owner,
                                                 Dream.status != "deleted")) is None:
        raise HTTPException(404, "Traitement inaccessible")
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update(nowait=True)
                    .execution_options(populate_existing=True))
    if job is None or job.cycle_key is None:
        raise HTTPException(409, "Job historique non relançable par P11.")
    dream = owned(db, owner, job.dream_id)
    if job.kind in {"image", "emotion"}:
        cls = ImageGeneration if job.kind == "image" else EmotionAnalysis
        snapshot = db.get(cls, job.id, populate_existing=True)
        if (snapshot is None or snapshot.user_id != owner
                or snapshot.text_version != dream.text_version
                or snapshot.transcript != dream.transcript):
            raise rules.JobRuleError("stale_result")
        if job.kind == "image":
            description = db.get(ImageDescription, dream.id, populate_existing=True)
            if (description is None or description.description != snapshot.description
                    or description.version != snapshot.description_version
                    or description.text_version != dream.text_version):
                raise rules.JobRuleError("stale_result")
    return job, dream


def retry_job(sessions, owner, job_id, *, engine, explicit=False):
    with sessions() as db:
        try:
            bounded(db)
            job, dream = lock_job(db, owner, job_id)
            identity = inputs_for(db, dream, job.kind, engine, media_id=job.media_id)
            rows = cycle_rows(db, dream, identity)
            if any(j.status in {"queued", "running"} for j in rows if j.id != job.id):
                raise rules.JobRuleError("active_conflict")
            if identity.cycle_key != job.cycle_key or not rows or rows[-1].id != job.id:
                raise rules.JobRuleError("stale_result")
            snapshot = state_for(db, job, rows)
            meta = db.get(DreamEmotion, dream.id) if job.kind == "emotion" else None
            updated = rules.retry(snapshot, db.scalar(select(func.clock_timestamp())),
                inputs=identity, explicit=explicit, choice_revision=meta.revision if meta else None)
            ai_quota.check(db, owner)
            job.retry_count += updated.retry_count - snapshot.retry_count
            job.status, job.queued_at, job.error_code = "queued", updated.queued_at, None
            job.finished_at = job.claim_token = job.lease_until = None
            if meta:
                meta.active_request = job.id
            db.commit()
            return job.id
        except (SQLAlchemyError, rules.JobRuleError, HTTPException, ValidationError) as exc:
            db.rollback()
            raise translate_error(exc) from None


def reserve_job(sessions, owner, job_id, *, engine, token, policy=rules.Policy()):
    """Réservation commune des consommateurs, bornée par le budget persistant."""
    with sessions() as db:
        try:
            bounded(db)
            job, dream = lock_job(db, owner, job_id)
            identity = inputs_for(db, dream, job.kind, engine, media_id=job.media_id)
            if identity.cycle_key != job.cycle_key:
                raise rules.JobRuleError("stale_result")
            before = state_for(db, job, cycle_rows(db, dream, identity))
            meta = db.get(DreamEmotion, dream.id) if job.kind == "emotion" else None
            updated = rules.reserve(before, db.scalar(select(func.clock_timestamp())), token,
                inputs=identity, choice_revision=meta.revision if meta else None, policy=policy)
            ai_quota.admit(db, owner, job, token,
                           job.attempts + updated.attempts - before.attempts)
            job.attempts += updated.attempts - before.attempts
            job.status, job.claim_token, job.lease_until = "running", token, updated.lease_until
            db.commit()
            return token
        except (SQLAlchemyError, rules.JobRuleError, HTTPException, ValidationError) as exc:
            db.rollback()
            raise translate_error(exc) from None


def enqueue_existing(db, owner, dream_id, kind, parameters, **versions):
    """Point d'entrée unique des routes existantes ; aucune nouvelle route de relance."""
    from backend.app.job_config import identity
    try:
        approved = identity(parameters)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "Configuration du moteur indisponible") from None
    identifier = create(lambda: nullcontext(db), owner, dream_id, kind,
                        engine=approved, parameters=parameters,
                        explicit=True, **versions)
    return db.get(Job, identifier)


def claim_next(sessions, kind, timeout):
    """Récupère les expirations sans IA, puis réserve un seul job via les règles P11."""
    from backend.app.services.job_maintenance import maintain
    if type(timeout) is not int or not 1 <= timeout <= 1800:
        raise ValueError("Délai invalide")
    policy = rules.Policy(queued_seconds=int(os.getenv("P11_QUEUE_TIMEOUT_SECONDS", "1800")),
                          **{f"{kind}_seconds": timeout})
    maintain(sessions, apply=True, policy=policy)
    with sessions() as db:
        candidates = list(db.execute(select(Job.id, Dream.user_id, Job.input_snapshot)
            .join(Dream).where(Job.kind == kind, Job.status == "queued",
                                Dream.status != "deleted",
                                Dream.user_id.not_in(ai_quota.exhausted_accounts()))
            .order_by(Job.queued_at, Job.id).limit(100)))
    for identifier, owner, raw in candidates:
        if raw is None:
            # Pas d'adoption automatique d'un historique sans configuration fiable.
            with sessions() as db:
                bounded(db)
                job = db.scalar(select(Job).where(Job.id == identifier)
                                .with_for_update(skip_locked=True))
                if job and job.status == "queued" and job.cycle_key is None:
                    job.status, job.error_code = "failed", "configuration"
                    job.finished_at = db.scalar(select(func.clock_timestamp()))
                    job.claim_token = job.lease_until = None
                    meta = db.get(DreamEmotion, job.dream_id)
                    if meta and meta.active_request == job.id:
                        meta.active_request = None
                    db.commit()
            continue
        try:
            inputs = read_inputs(raw)
            token = uuid4()
            reserve_job(sessions, owner, identifier, engine=inputs.engine,
                        token=token, policy=policy)
            return identifier, token
        except (HTTPException, ValidationError) as exc:
            if isinstance(exc, HTTPException) and exc.status_code == 503:
                raise
            if isinstance(exc, HTTPException) and (exc.headers or {}).get("Retry-After"):
                continue  # Contention temporaire : ne pas déclarer les entrées périmées.
            # Entrées périmées : échec contrôlé, jamais de calcul pour les réparer.
            with sessions() as db:
                bounded(db)
                job = db.scalar(select(Job).where(Job.id == identifier)
                                .with_for_update(skip_locked=True))
                if job and job.status == "queued":
                    job.status, job.error_code = "failed", (
                        "stale_result" if kind == "emotion" else "text_conflict")
                    now = db.scalar(select(func.clock_timestamp()))
                    if job.queued_at <= now-timedelta(seconds=policy.queued_seconds):
                        job.error_code = "queue_timeout"
                    job.finished_at = now
                    meta = db.get(DreamEmotion, job.dream_id)
                    if meta and meta.active_request == job.id:
                        meta.active_request = None
                    db.commit()
    return None


def read_inputs(raw):
    return rules.Inputs.model_validate_json(json.dumps(
        {key: value for key, value in raw.items() if not key.startswith("_")}))


def publication_guard(db, job):
    """À appeler avec le job verrouillé ; refus des anciens binaires non identifiés."""
    if job.cycle_key is None:
        raise HTTPException(409, "Historique non versionné")
    inputs = read_inputs(job.input_snapshot)
    _, dream = lock_job(db, inputs.owner_id, job.id)
    current = inputs_for(db, dream, job.kind, inputs.engine, media_id=job.media_id)
    if current.cycle_key != job.cycle_key:
        raise HTTPException(409, "Entrées modifiées")
    state = state_for(db, job, cycle_rows(db, dream, current))
    meta = db.get(DreamEmotion, dream.id) if job.kind == "emotion" else None
    try:
        rules.current(state, current, True, meta.revision if meta else None)
    except rules.JobRuleError:
        raise HTTPException(409, "Contexte modifié") from None
    ai_quota.verify_admission(db, inputs.owner_id, job)
    return dream


def stop_reservation(sessions, job_id, token):
    """Arrêt coopératif ; si PostgreSQL est absent, le bail reste récupérable."""
    try:
        with sessions() as db:
            bounded(db)
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update(nowait=True))
            if job and job.status == "running" and job.claim_token == token:
                job.status, job.error_code = "failed", "worker_stopped"
                job.finished_at = db.scalar(select(func.clock_timestamp()))
                job.claim_token = job.lease_until = None
                meta = db.get(DreamEmotion, job.dream_id)
                if meta and meta.active_request == job.id:
                    meta.active_request = None
                db.commit()
    except SQLAlchemyError:
        pass
