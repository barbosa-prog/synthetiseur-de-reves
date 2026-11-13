"""File PostgreSQL persistante, réservations expirables et publication atomique P06."""


from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.models import Dream, Job, Media
from backend.app.services.media import MediaNotFound
from backend.app.services.transcripts import TextVersionConflict, apply_correction
from backend.app.storage.local import StorageError
from backend.app.stt_provider import STTError

PUBLIC_STATES = {"queued": "pending", "running": "processing", "done": "completed",
                 "failed": "failed"}
MESSAGES = {
    "timeout": "Le délai de transcription est dépassé. Vous pouvez réessayer.",
    "text_conflict": "Votre récit a changé. Votre correction a été conservée.",
    "insufficient_memory": "Mémoire insuffisante sur le PC. Libérez de la RAM puis réessayez.",
    "model_unavailable": "Le modèle local n'est pas encore disponible.",
    "memory_unknown": "La mémoire disponible n'a pas pu être vérifiée.",
    "invalid_text": "Le résultat est vide ou dépasse la longueur acceptée.",
    "media_unavailable": "L'audio n'est plus disponible.",
    "interrupted": "Le traitement a été interrompu à plusieurs reprises.",
    "provider_failed": "La transcription locale a échoué. La saisie manuelle reste disponible.",
    "provider_unavailable": "Le moteur local est indisponible.",
    "configuration": "La configuration du moteur doit être vérifiée.",
    "queue_timeout": "Le délai d'attente est dépassé. Aucun traitement n'a été relancé.",
    "worker_stopped": "Le traitement a été arrêté.",
}


def projection(job, db=None, owner=None):
    """Aucun contenu, chemin, jeton de réservation ni détail d'exception."""
    result = {"id": job.id, "dream_id": job.dream_id, "media_id": job.media_id,
            "status": PUBLIC_STATES[job.status], "attempts": job.attempts,
            "error_code": job.error_code,
            "message": MESSAGES.get(job.error_code, MESSAGES["provider_failed"])
            if job.error_code else None}
    if db is not None:
        from backend.app.services.job_tracking import project, safe_error
        result["tracking"] = project(db, owner, job)
        result["error_code"] = safe_error(job.error_code)
    return result


def enqueue(db, user_id, dream_id, media_id, expected_version):
    from backend.app.job_config import stt_parameters
    from backend.app.services.job_lifecycle import enqueue_existing
    try:
        parameters = stt_parameters()
    except (STTError, ValueError):
        raise HTTPException(503, "Configuration du moteur indisponible") from None
    return enqueue_existing(db, user_id, dream_id, "stt", parameters,
                            text_version=expected_version, media_id=media_id)



def owned_job(db, user_id, job_id):
    job = db.scalar(select(Job).join(Dream).where(
        Job.id == job_id, Job.kind == "stt", Dream.user_id == user_id, Dream.status != "deleted",
    ))
    if job is None:
        raise HTTPException(404, "Traitement inaccessible")
    return job


def claim(sessions, timeout):
    from backend.app.services.job_lifecycle import claim_next
    return claim_next(sessions, "stt", timeout)



def run_once(sessions, media_service, provider):
    """Un appel fournisseur hors transaction ; résultat publié seulement avec le bail courant."""
    reservation = claim(sessions, provider.timeout)
    if reservation is None:
        return False
    identifier, token = reservation
    error, output = None, None
    try:
        with sessions() as db:
            job = db.get(Job, identifier)
            if job is None:
                return True
            dream = db.get(Dream, job.dream_id)
            if dream is None or dream.status == "deleted" or (
                dream.text_version != job.expected_text_version
            ):
                raise STTError("text_conflict")
            user_id, media_id = dream.user_id, job.media_id
            from backend.app.job_config import identity, stt_parameters
            from backend.app.services.job_lifecycle import read_inputs
            from backend.app.stt_provider import LocalWhisper
            if isinstance(provider, LocalWhisper):
                approved = identity(stt_parameters(provider.config))
                if (approved.model_revision == "local-unverified"
                        or read_inputs(job.input_snapshot).engine != approved):
                    raise STTError("configuration")
        audio = media_service.download(user_id, media_id)
        with audio.stream:
            content = audio.stream.read(15 * 1024**2 + 1)
        if len(content) > 15 * 1024**2:
            raise STTError("media_unavailable")
        output = provider.transcribe(content)
    except KeyboardInterrupt:
        from backend.app.services.job_lifecycle import stop_reservation
        stop_reservation(sessions, identifier, token)
        raise
    except STTError as exc:
        error = str(exc) if str(exc) in MESSAGES else "provider_failed"
    except (MediaNotFound, StorageError):
        error = "media_unavailable"
    except Exception:
        error = "provider_failed"
    with sessions() as db:
        from backend.app.services.job_lifecycle import bounded
        bounded(db)
        job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
        now = db.scalar(select(func.clock_timestamp()))
        if (job is None or job.status != "running" or job.claim_token != token
                or job.lease_until is None or job.lease_until <= now):
            return True  # Ancien worker : aucun droit de publier, même s'il revient tard.
        dream = db.scalar(select(Dream).where(Dream.id == job.dream_id).with_for_update())
        media = db.get(Media, job.media_id)
        if not error:
            if dream.status == "deleted":
                error = "text_conflict"
            elif (media is None or media.dream_id != dream.id or media.storage_state != "ready"
                  or (media.expires_at is not None and media.expires_at <= now)):
                error = "media_unavailable"
            else:
                try:
                    from backend.app.services.job_lifecycle import publication_guard
                    publication_guard(db, job)
                    apply_correction(db, dream, output, job.expected_text_version)
                    from backend.app.job_rules import content_digest
                    job.input_snapshot = {**job.input_snapshot, "_output": {
                        "text_version": dream.text_version,
                        "text_digest": content_digest(dream.transcript)}}
                except TextVersionConflict:
                    error = "text_conflict"
                except HTTPException:
                    error = "text_conflict"
                except (ValueError, TypeError):
                    error = "invalid_text"
        job.status = "failed" if error else "done"
        job.error_code, job.finished_at = error, now
        job.claim_token, job.lease_until = None, None
        db.commit()
    return True
