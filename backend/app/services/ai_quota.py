"""Quota PostgreSQL glissant : uniquement appelé dans une transaction P11 bornée."""

import math
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, text

from backend.app.models import AIExecution, AIQuotaPolicy

WINDOW = timedelta(hours=24)


def clock(db):
    return db.scalar(select(func.clock_timestamp())).astimezone(timezone.utc)


def exhausted_accounts():
    """Préfiltre de file, non décisionnel ; l'admission verrouillée reste obligatoire."""
    maximum = select(AIQuotaPolicy.execution_limit).where(
        AIQuotaPolicy.id == 1).scalar_subquery()
    return (select(AIExecution.user_id)
            .where(AIExecution.admitted_at > func.clock_timestamp()-text("INTERVAL '24 hours'"))
            .group_by(AIExecution.user_id).having(func.count() >= maximum))


def check(db, owner):
    """Sérialise le compte après les verrous job/rêve ; aucune unité réservée ici.

    Le verrou partagé de politique empêche une reconfiguration en cours de décision.
    L'heure est relue après acquisition des verrous, jamais fournie par le client.
    """
    # Un instantané REPEATABLE READ pris avant l'attente du verrou pourrait cacher
    # l'unité qu'un autre processus vient de valider. Refuser cette configuration.
    if db.scalar(text("SHOW transaction_isolation")) != "read committed":
        raise HTTPException(503, "Configuration transactionnelle du quota indisponible")
    policy = db.scalar(select(AIQuotaPolicy).where(AIQuotaPolicy.id == 1)
                       .with_for_update(read=True).execution_options(populate_existing=True))
    if policy is None:
        raise HTTPException(503, "Configuration du quota indisponible")
    # Espace de verrou dédié ; une collision ne ferait que sérialiser deux comptes.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 1212))"),
               {"key": str(owner)})
    now = clock(db)
    active = (AIExecution.user_id == owner, AIExecution.admitted_at > now-WINDOW)
    used = db.scalar(select(func.count()).select_from(AIExecution).where(*active))
    if used >= policy.execution_limit:
        release = db.scalar(select(AIExecution.admitted_at).where(*active)
                            .order_by(AIExecution.admitted_at, AIExecution.id)
                            .offset(used-policy.execution_limit).limit(1))
        retry = max(1, math.ceil((release.astimezone(timezone.utc)+WINDOW-now).total_seconds()))
        raise HTTPException(429, "Quota de calcul temporairement atteint",
                            headers={"Retry-After": str(retry), "Cache-Control": "no-store"})
    return now


def admit(db, owner, job, token, attempt):
    """Même transaction que queued→running : tout est validé ou tout est annulé."""
    admitted_at = check(db, owner)
    db.add(AIExecution(user_id=owner, job_id=job.id, kind=job.kind, attempt=attempt,
                       reservation_token=token, admitted_at=admitted_at))


def verify_admission(db, owner, job):
    """Un résultat ne peut être publié sans l'admission de cette réservation."""
    admitted = db.scalar(select(AIExecution.id).where(
        AIExecution.user_id == owner, AIExecution.job_id == job.id,
        AIExecution.attempt == job.attempts,
        AIExecution.reservation_token == job.claim_token))
    if admitted is None:
        raise HTTPException(409, "Traitement sans admission valide")


def configure(db, limit):
    """Reconfiguration explicite, pas une variable locale divergente entre workers."""
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("Limite de quota invalide")
    policy = db.scalar(select(AIQuotaPolicy).where(AIQuotaPolicy.id == 1).with_for_update())
    if policy is None:
        raise ValueError("Politique de quota absente")
    policy.execution_limit = limit
    db.flush()
