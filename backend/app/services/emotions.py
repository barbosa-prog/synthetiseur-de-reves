"""P08 PostgreSQL : aucune attribution automatique, aucun import de moteur IA."""

import json

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app import emotion_rules as rules
from backend.app.emotion_config import parameters as runtime_parameters
from backend.app.emotion_provider import EmotionError, EmotionRequest, EmotionResult, analyze
from backend.app.models import Dream, DreamEmotion, EmotionAnalysis, Job
from backend.app.services.transcripts import owned_dream


def metadata(db, dream):
    """À appeler avec verrou du rêve ; initialise les nouveaux rêves paresseusement."""
    row = db.get(DreamEmotion, dream.id, populate_existing=True)
    if row is None:
        row = DreamEmotion(
            dream_id=dream.id, source="legacy" if dream.emotion else "unset", revision=0
        )
        db.add(row)
        db.flush()
    return row


def state_for(db, dream, meta):
    suggestion = None
    if meta.suggestion_id:
        snapshot = db.get(EmotionAnalysis, meta.suggestion_id, populate_existing=True)
        job = db.get(Job, meta.suggestion_id, populate_existing=True)
        if (
            snapshot
            and job
            and job.kind == "emotion"
            and job.dream_id == dream.id
            and job.status == "done"
            and snapshot.user_id == dream.user_id
            and snapshot.text_version == dream.text_version
            and snapshot.transcript == dream.transcript
            and snapshot.result
        ):
            suggestion = EmotionResult.model_validate_json(json.dumps(snapshot.result))
    return rules.EmotionState(
        text_version=dream.text_version,
        revision=meta.revision,
        value=dream.emotion,
        source=meta.source,
        selected_text_version=meta.selected_text_version,
        active_request=meta.active_request,
        suggestion=suggestion,
    )


def save_state(db, dream, meta, state, *, update_choice=True):
    if update_choice:
        dream.emotion = state.value
    meta.source, meta.revision = state.source, state.revision
    meta.selected_text_version = state.selected_text_version
    meta.active_request = state.active_request
    meta.suggestion_id = state.suggestion.request_id if state.suggestion else None
    meta.updated_at = db.scalar(select(func.clock_timestamp()))


def translate(operation, *args):
    try:
        return operation(*args)
    except EmotionError:
        raise HTTPException(409, "Choix, récit ou suggestion modifié ; rechargez.") from None


def projection(db, user_id, dream_id):
    dream = owned_dream(db, user_id, dream_id, lock=True)
    meta = metadata(db, dream)
    state = state_for(db, dream, meta)
    result = state.model_dump(mode="json")
    # Cet identifiant est un UUID métier, jamais le token de réservation.
    result["warning"] = "Suggestion indicative, non médicale. À confirmer ou corriger."
    return result


def set_choice(db, dream, value, expected_revision=None):
    """Pas de commit : réutilisable dans l'ancien PATCH récit + émotion atomique."""
    meta = metadata(db, dream)
    state = state_for(db, dream, meta)
    expected = state.revision if expected_revision is None else expected_revision
    updated = translate(rules.choose, state, value, expected)
    save_state(db, dream, meta, updated)


def correct(db, user_id, dream_id, value, revision):
    dream = owned_dream(db, user_id, dream_id, lock=True)
    set_choice(db, dream, value, revision)
    db.commit()
    return projection(db, user_id, dream_id)


def accept(db, user_id, dream_id, suggestion_id, revision):
    dream = owned_dream(db, user_id, dream_id, lock=True)
    meta = metadata(db, dream)
    state = translate(rules.accept, state_for(db, dream, meta), suggestion_id, revision)
    save_state(db, dream, meta, state)
    db.commit()
    return projection(db, user_id, dream_id)


def invalidate_for_text(db, dream, new_version):
    """P06 appelle avant d'incrémenter sa version, sous son verrou de rêve."""
    meta = db.get(DreamEmotion, dream.id, populate_existing=True)
    if meta is not None:
        state = rules.text_changed(state_for(db, dream, meta), new_version)
        save_state(db, dream, meta, state)


def enqueue(db, user_id, dream_id, text_version, revision, *, parameters=None):
    from backend.app.services.job_lifecycle import enqueue_existing
    job = enqueue_existing(db, user_id, dream_id, "emotion",
                           dict(runtime_parameters() if parameters is None else parameters),
                           text_version=text_version, choice_revision=revision)
    return job_projection(db, user_id, job.id)



def owned_job(db, user_id, job_id, *, lock=False):
    statement = (
        select(Job)
        .join(Dream)
        .where(
            Job.id == job_id,
            Job.kind == "emotion",
            Dream.user_id == user_id,
            Dream.status != "deleted",
        )
    )
    if lock:
        statement = statement.with_for_update(of=Job).execution_options(populate_existing=True)
    job = db.scalar(statement)
    if job is None:
        raise HTTPException(404, "Traitement inaccessible")
    return job


def job_projection(db, user_id, job_id):
    job = owned_job(db, user_id, job_id)
    snapshot = db.get(EmotionAnalysis, job_id, populate_existing=True)
    dream = db.get(Dream, job.dream_id, populate_existing=True)
    meta = db.get(DreamEmotion, job.dream_id, populate_existing=True)
    outdated_reservation = job.status in {"queued", "running"} and (
        meta is None or meta.active_request != job.id or meta.revision != snapshot.choice_revision
    )
    from backend.app.services.job_tracking import project, safe_error
    return dict(
        tracking=project(db, user_id, job),
        id=job.id,
        dream_id=job.dream_id,
        status=job.status,
        attempts=job.attempts,
        error_code=safe_error(job.error_code),
        text_version=snapshot.text_version,
        stale=(
            dream.text_version != snapshot.text_version
            or job.error_code == "stale_result"
            or outdated_reservation
        ),
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def current(db, job):
    """Ordre des verrous partagé : job puis rêve ; mutations manuelles : rêve seulement."""
    dream = db.scalar(
        select(Dream)
        .where(Dream.id == job.dream_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    snapshot = db.get(EmotionAnalysis, job.id, populate_existing=True)
    meta = db.get(DreamEmotion, job.dream_id, populate_existing=True)
    valid = bool(
        dream
        and snapshot
        and meta
        and dream.status != "deleted"
        and dream.user_id == snapshot.user_id
        and dream.text_version == snapshot.text_version == job.expected_text_version
        and dream.transcript == snapshot.transcript
        and meta.active_request == job.id
        and meta.revision == snapshot.choice_revision
    )
    return valid, dream, snapshot, meta


def terminate(db, job, code):
    job.status, job.error_code = "failed", code
    job.claim_token = job.lease_until = None
    job.finished_at = db.scalar(select(func.clock_timestamp()))
    meta = db.get(DreamEmotion, job.dream_id, populate_existing=True)
    if meta and meta.active_request == job.id:
        meta.active_request = None


def claim(sessions, timeout=30):
    from backend.app.services.job_lifecycle import claim_next
    return claim_next(sessions, "emotion", timeout)



def cancel(db, user_id, job_id):
    job = owned_job(db, user_id, job_id, lock=True)
    # Même ordre de verrou que publication et reprise, jamais rêve puis job.
    owned_dream(db, user_id, job.dream_id, lock=True)
    if job.status in {"queued", "running"}:
        terminate(db, job, "cancelled")
    db.commit()


def finish(sessions, job_id, token, result=None, error=None):
    """Une seule transaction de validation/publication ; aucun choix implicite."""
    with sessions() as db:
        from backend.app.services.job_lifecycle import bounded
        bounded(db)
        job = db.scalar(
            select(Job)
            .where(Job.id == job_id, Job.kind == "emotion")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = db.scalar(select(func.clock_timestamp()))
        if (
            job is None
            or job.status != "running"
            or job.claim_token != token
            or job.lease_until is None
            or job.lease_until <= now
        ):
            return False
        valid, dream, snapshot, meta = current(db, job)
        if valid:
            from backend.app.services.job_lifecycle import publication_guard
            try:
                publication_guard(db, job)
            except HTTPException:
                valid = False
        if not valid:
            terminate(db, job, "stale_result")
        elif error:
            terminate(
                db,
                job,
                error
                if error
                in {
                    "timeout",
                    "worker_stopped",
                    "invalid_result",
                    "disabled",
                    "configuration",
                    "model_unavailable",
                    "insufficient_memory",
                    "worker_busy",
                    "stale_result",
                }
                else "provider_failed",
            )
        else:
            try:
                result = EmotionResult.model_validate(result.model_dump())
                if (
                    result.engine != snapshot.parameters["engine"]
                    or result.model_revision != snapshot.parameters["model_revision"]
                ):
                    raise EmotionError("invalid_result")
                state = rules.publish(state_for(db, dream, meta), result)
            except (EmotionError, ValueError, AttributeError, KeyError):
                terminate(db, job, "invalid_result")
            else:
                snapshot.result = result.model_dump(mode="json")
                save_state(db, dream, meta, state, update_choice=False)
                job.status, job.error_code, job.finished_at = "done", None, now
                job.claim_token = job.lease_until = None
        db.commit()
        return job.status == "done"


def run_once(sessions, provider, *, timeout=30, required_parameters=None):
    """Noyau testable avec faux fournisseur ; aucun worker IA ni timeout système ici."""
    reservation = claim(sessions, timeout=timeout)
    if reservation is None:
        return False
    identifier, token = reservation
    with sessions() as db:
        job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if job is None:
            return True  # Purge P10 entre réservation et lecture de l'instantané.
        valid, _, snapshot, _ = current(db, job)
        if job.claim_token != token:
            return False
        if not valid:
            terminate(db, job, "stale_result")
            db.commit()
            return True
        if required_parameters is not None and snapshot.parameters != required_parameters:
            terminate(db, job, "configuration")
            db.commit()
            return True
        request = EmotionRequest(
            request_id=identifier,
            text=snapshot.transcript,
            text_version=snapshot.text_version,
            choice_revision=snapshot.choice_revision,
        )
    try:
        result = analyze(provider, request)
    except KeyboardInterrupt:
        from backend.app.services.job_lifecycle import stop_reservation
        stop_reservation(sessions, identifier, token)
        raise
    except EmotionError as exc:
        finish(sessions, identifier, token, error=str(exc))
    else:
        finish(sessions, identifier, token, result)
    return True
