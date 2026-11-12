"""File PostgreSQL persistante, réservations expirables et publication atomique P06."""

import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.models import Dream, Job, Media
from backend.app.services.media import MediaNotFound
from backend.app.services.transcripts import TextVersionConflict, apply_correction, owned_dream
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
}


def projection(job):
    """Aucun contenu, chemin, jeton de réservation ni détail d'exception."""
    return {"id": job.id, "dream_id": job.dream_id, "media_id": job.media_id,
            "status": PUBLIC_STATES[job.status], "attempts": job.attempts,
            "error_code": job.error_code,
            "message": MESSAGES.get(job.error_code) if job.error_code else None}


def enqueue(db, user_id, dream_id, media_id, expected_version):
    """Verrou du rêve + index unique : même audio/rêve jamais deux fois simultanément."""
    dream = owned_dream(db, user_id, dream_id, lock=True)
    media = db.scalar(select(Media).where(
        Media.id == media_id, Media.dream_id == dream.id, Media.kind == "audio",
        Media.storage_state == "ready", Media.audio_source.is_not(None),
        (Media.expires_at.is_(None) | (Media.expires_at > func.now())),
    ))
    if media is None:
        raise HTTPException(404, "Audio inaccessible")
    if dream.text_version != expected_version:
        raise HTTPException(409, "Le récit a changé ; rechargez la page")
    active = db.scalar(select(Job).where(
        Job.dream_id == dream_id, Job.kind == "stt", Job.status.in_(["queued", "running"]),
    ))
    if active:
        raise HTTPException(409, "Une transcription est déjà en cours")
    job = Job(dream_id=dream_id, media_id=media_id, kind="stt",
              expected_text_version=expected_version)
    db.add(job)
    db.commit()
    return job


def owned_job(db, user_id, job_id):
    job = db.scalar(select(Job).join(Dream).where(
        Job.id == job_id, Job.kind == "stt", Dream.user_id == user_id, Dream.status != "deleted",
    ))
    if job is None:
        raise HTTPException(404, "Traitement inaccessible")
    return job


def claim(sessions, timeout):
    """SKIP LOCKED pour plusieurs workers ; jeton distinct à chaque reprise."""
    with sessions() as db:
        now = db.scalar(select(func.clock_timestamp()))
        expired = db.scalars(select(Job).where(
            Job.kind == "stt", Job.status == "running",
            (Job.lease_until.is_(None) | (Job.lease_until <= now)),
        ).with_for_update(skip_locked=True)).all()
        for job in expired:
            job.status = "failed" if job.attempts >= 3 else "queued"
            job.claim_token = None
            job.lease_until = None
            if job.status == "failed":
                job.error_code, job.finished_at = "interrupted", now
        db.flush()
        job = db.scalar(select(Job).where(
            Job.kind == "stt", Job.status == "queued",
        ).order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            db.commit()
            return None
        if job.attempts >= 3 or job.media_id is None or job.expected_text_version is None:
            job.status, job.error_code, job.finished_at = "failed", "interrupted", now
            db.commit()
            return None
        job.status, job.attempts = "running", job.attempts + 1
        job.claim_token = uuid.uuid4()
        job.lease_until = now + timedelta(seconds=timeout + 60)
        token = job.claim_token
        identifier = job.id
        db.commit()
        return identifier, token


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
            dream = db.get(Dream, job.dream_id)
            if dream.status == "deleted" or dream.text_version != job.expected_text_version:
                raise STTError("text_conflict")
            user_id, media_id = dream.user_id, job.media_id
        audio = media_service.download(user_id, media_id)
        with audio.stream:
            content = audio.stream.read(15 * 1024**2 + 1)
        if len(content) > 15 * 1024**2:
            raise STTError("media_unavailable")
        output = provider.transcribe(content)
    except STTError as exc:
        error = str(exc) if str(exc) in MESSAGES else "provider_failed"
    except (MediaNotFound, StorageError):
        error = "media_unavailable"
    except Exception:
        error = "provider_failed"
    with sessions() as db:
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
                    apply_correction(db, dream, output, job.expected_text_version)
                except TextVersionConflict:
                    error = "text_conflict"
                except (ValueError, TypeError):
                    error = "invalid_text"
        job.status = "failed" if error else "done"
        job.error_code, job.finished_at = error, now
        job.claim_token, job.lease_until = None, None
        db.commit()
    return True
