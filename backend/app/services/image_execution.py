"""Publication P19 et job dans une transaction, avec compensation des fichiers."""

import io

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.image_provider import ImageError, ImageRequest, validate_result
from backend.app.image_worker import ImageTask, prepare_image
from backend.app.models import ImageDescription, ImageGeneration, Job, Media
from backend.app.services import image_jobs
from backend.app.services.media import lock_key
from backend.app.storage.local import new_key


def publish(sessions, storage, task, token, result):
    validate_result(result, task.request)
    key = new_key()
    attempted = False
    try:
        with sessions() as db:
            snapshot = image_jobs.authorize_publication(db, task.user_id, task.job_id, token)
            job = db.get(Job, task.job_id)
            if (job.dream_id != task.dream_id or snapshot.description != task.request.description
                    or snapshot.text_version != task.request.text_version
                    or snapshot.description_version != task.request.description_version):
                raise ImageError("text_conflict")
            lock_key(db, key)
            attempted = True
            stored = storage.write(io.BytesIO(result.png), key=key, kind="image",
                                   media_format="png")
            media = Media(dream_id=task.dream_id, kind="image", storage_key=stored.key,
                          size_bytes=stored.size, media_type=stored.media_type,
                          sha256=stored.sha256,
                          storage_state="ready")
            db.add(media)
            db.flush()
            # Le bail peut avoir expiré pendant l'écriture ; garde à nouveau avant commit.
            image_jobs.authorize_publication(db, task.user_id, task.job_id, token)
            job = db.get(Job, task.job_id)
            job.status, job.media_id = "done", media.id
            job.finished_at = db.scalar(select(func.clock_timestamp()))
            job.claim_token = job.lease_until = None
            job.error_code = None
            db.commit()
            return media.id
    except Exception:
        if attempted:
            try:
                with sessions() as db:
                    lock_key(db, key)
                    if db.scalar(select(Media.id).where(Media.storage_key == key)) is None:
                        storage.delete(key)
                    db.commit()
            except Exception:
                pass  # Réconciliation P19 après délai de grâce si DB/FS indisponible.
        raise


def current_image(db, user_id, dream_id):
    """Image actuelle calculée par versions ; une correction invalide immédiatement le lien."""
    from backend.app.services.transcripts import owned_dream
    dream = owned_dream(db, user_id, dream_id, lock=True)
    description = db.get(ImageDescription, dream_id, populate_existing=True)
    if description is None or description.text_version != dream.text_version:
        return None
    return db.scalar(select(Media.id).join(Job, Job.media_id == Media.id)
        .join(ImageGeneration, ImageGeneration.job_id == Job.id).where(
            Job.dream_id == dream_id, Job.kind == "image", Job.status == "done",
            ImageGeneration.user_id == user_id, ImageGeneration.text_version == dream.text_version,
            ImageGeneration.description_version == description.version,
            ImageGeneration.transcript == dream.transcript,
            ImageGeneration.description == description.description,
            Media.dream_id == dream_id, Media.kind == "image", Media.storage_state == "ready",
            (Media.expires_at.is_(None) | (Media.expires_at > func.now())),
        ).order_by(Job.finished_at.desc(), Job.id.desc()).limit(1))


def run_once(sessions, storage, provider):
    """L'appelant détient le verrou GPU OS pendant claim/calcul/publication."""
    reservation = image_jobs.claim(sessions)
    if reservation is None:
        return False
    identifier, token = reservation
    with sessions() as db:
        job = db.get(Job, identifier)
        snapshot = db.get(ImageGeneration, identifier)
        if job is None or snapshot is None:
            return True  # Purge P10 après réservation : aucun droit de publier.
        task = ImageTask(identifier, job.dream_id, snapshot.user_id, ImageRequest(
            description=snapshot.description, text_version=snapshot.text_version,
            description_version=snapshot.description_version, seed=snapshot.parameters["seed"]))

    def current(_):
        with sessions() as db:
            try:
                image_jobs.authorize_publication(db, task.user_id, identifier, token)
                return True
            except HTTPException:
                return False

    try:
        from backend.app.image_provider import LocalStableDiffusion15
        from backend.app.job_config import image_parameters
        if isinstance(provider, LocalStableDiffusion15) and (
            snapshot.parameters != image_parameters(task.request.seed)
        ):
            raise ImageError("configuration")
        result = prepare_image(task, provider, current)
        publish(sessions, storage, task, token, result)
    except KeyboardInterrupt:
        from backend.app.services.job_lifecycle import stop_reservation
        stop_reservation(sessions, identifier, token)
        raise
    except Exception as exc:
        code = str(exc) if isinstance(exc, ImageError) else "provider_failed"
        try:
            image_jobs.fail(sessions, task.user_id, identifier, token, code)
        except HTTPException:
            pass  # Rêve supprimé : reprise expirée assurera le nettoyage du job.
    return True
