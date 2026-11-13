"""File image PostgreSQL uniquement ; aucune IA ni publication de fichier."""


from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.image_provider import ImageRequest
from backend.app.models import Dream, ImageDescription, ImageGeneration, Job
from backend.app.services.transcripts import owned_dream

ERRORS = {"timeout", "provider_failed", "safety_blocked", "interrupted", "text_conflict",
          "model_unavailable", "insufficient_memory", "cancelled", "worker_stopped",
          "configuration"}


def description_for(db, user_id, dream_id):
    owned_dream(db, user_id, dream_id)
    return db.get(ImageDescription, dream_id)


def save_description(db, user_id, dream_id, description, text_version, expected_version):
    """Version 0 pour création ; même texte reconfirmé après P06 devient une nouvelle version."""
    request = ImageRequest(description=description, text_version=text_version,
                           description_version=1)
    dream = owned_dream(db, user_id, dream_id, lock=True)
    if not dream.transcript or dream.text_version != text_version:
        raise HTTPException(409, "Le récit a changé ou est absent")
    current = db.get(ImageDescription, dream_id, populate_existing=True)
    if expected_version != (current.version if current else 0):
        raise HTTPException(409, "La description a changé")
    if current is None:
        current = ImageDescription(dream_id=dream_id, description=request.description,
                                   version=1, text_version=text_version)
        db.add(current)
    elif current.description != request.description or current.text_version != text_version:
        current.description = request.description
        current.text_version = text_version
        current.version += 1
        current.updated_at = db.scalar(select(func.clock_timestamp()))
    db.commit()
    return current


def enqueue(db, user_id, dream_id, text_version, description_version, *, seed=42,
            new_generation=False, media_service=None):
    from backend.app.job_config import image_parameters
    from backend.app.services.job_lifecycle import enqueue_existing
    return enqueue_existing(db, user_id, dream_id, "image", image_parameters(seed),
                            text_version=text_version, description_version=description_version,
                            new_image=new_generation, media_service=media_service)



def owned_job(db, user_id, job_id, *, lock=False):
    if lock:
        from backend.app.services.job_lifecycle import bounded
        bounded(db)
    query = select(Job).join(Dream).where(Job.id == job_id, Job.kind == "image",
                                         Dream.user_id == user_id, Dream.status != "deleted")
    if lock:
        query = query.with_for_update(of=Job).execution_options(populate_existing=True)
    job = db.scalar(query)
    if job is None:
        raise HTTPException(404, "Traitement inaccessible")
    return job


def projection(db, user_id, job_id):
    job = owned_job(db, user_id, job_id)
    return {"id": job.id, "dream_id": job.dream_id, "status": job.status,
            "attempts": job.attempts, "error_code": job.error_code,
            "created_at": job.created_at, "finished_at": job.finished_at}


def _fail(job, now, code):
    job.status, job.error_code, job.finished_at = "failed", code, now
    job.claim_token = job.lease_until = None


def _current(db, job):
    """Appeler avec verrou du job ; verrou du rêve commun aux écritures P06/description."""
    dream = db.scalar(select(Dream).where(Dream.id == job.dream_id).with_for_update()
                      .execution_options(populate_existing=True))
    snapshot = db.get(ImageGeneration, job.id, populate_existing=True)
    description = db.get(ImageDescription, job.dream_id, populate_existing=True)
    return bool(dream and snapshot and description and dream.status != "deleted"
                and dream.user_id == snapshot.user_id
                and dream.text_version == snapshot.text_version == job.expected_text_version
                and dream.transcript == snapshot.transcript
                and description.text_version == snapshot.text_version
                and description.version == snapshot.description_version
                and description.description == snapshot.description)


def claim(sessions, timeout=120):
    if type(timeout) is not int or not 30 <= timeout <= 600:
        raise ValueError("Délai image invalide")
    from backend.app.services.job_lifecycle import claim_next
    return claim_next(sessions, "image", timeout)



def authorize_publication(db, user_id, job_id, token):
    """Garde transactionnelle ; NE COMMIT PAS et ne publie rien.

    Le futur publisher doit référencer le média dans cette même transaction,
    sans libérer les verrous ni appeler un service qui commit séparément.
    """
    job = owned_job(db, user_id, job_id, lock=True)
    if job.status != "running" or job.claim_token != token:
        raise HTTPException(409, "Réservation image dépassée")
    if not _current(db, job):
        raise HTTPException(409, "Récit ou description modifiés")
    now = db.scalar(select(func.clock_timestamp()))
    if job.lease_until is None or job.lease_until <= now:
        raise HTTPException(409, "Réservation image expirée")
    from backend.app.services.job_lifecycle import publication_guard
    publication_guard(db, job)
    return db.get(ImageGeneration, job_id)


def fail(sessions, user_id, job_id, token, code):
    """Ancien worker sans droit de modifier le job repris ; aucune donnée fournisseur."""
    with sessions() as db:
        job = owned_job(db, user_id, job_id, lock=True)
        now = db.scalar(select(func.clock_timestamp()))
        if (job.status != "running" or job.claim_token != token
                or job.lease_until is None or job.lease_until <= now):
            return False
        _fail(job, now, code if code in ERRORS else "provider_failed")
        db.commit()
        return True


def cancel(db, user_id, job_id):
    job = owned_job(db, user_id, job_id, lock=True)
    if job.status in {"queued", "running"}:
        _fail(job, db.scalar(select(func.clock_timestamp())), "cancelled")
    db.commit()
