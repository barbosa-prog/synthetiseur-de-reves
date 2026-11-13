"""Réconciliation PostgreSQL seule : aucun import de fournisseur ou worker IA."""

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.job_rules import Policy
from backend.app.models import Dream, DreamEmotion, Job


def maintain(sessions, *, apply=False, limit=100, policy=Policy()):
    if type(apply) is not bool or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Configuration de maintenance invalide")
    from datetime import timedelta
    with sessions() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '10s'"))
        now = db.scalar(select(func.clock_timestamp()))
        ids = list(db.scalars(select(Job.id).join(Dream).where(
            Job.kind.in_(["stt", "image", "emotion"]), Job.status.in_(["queued", "running"]),
            or_(Dream.status == "deleted",
                (Job.status == "queued") & (Job.queued_at <= now-timedelta(
                    seconds=policy.queued_seconds)),
                (Job.status == "running") & or_(Job.lease_until.is_(None), Job.lease_until <= now)),
        ).order_by(Job.queued_at, Job.id).limit(limit)))
    report = dict(candidates=len(ids), failed=0, deferred=0)
    if not apply:
        return report
    for identifier in ids:
        with sessions() as db:
            try:
                db.execute(text("SET LOCAL lock_timeout = '3s'"))
                db.execute(text("SET LOCAL statement_timeout = '10s'"))
                job = db.scalar(select(Job).where(Job.id == identifier)
                                .with_for_update(skip_locked=True))
                if job is None or job.status not in {"queued", "running"}:
                    report["deferred"] += 1
                    continue
                dream = db.scalar(select(Dream).where(Dream.id == job.dream_id)
                                  .with_for_update(nowait=True))
                now = db.scalar(select(func.clock_timestamp()))
                error = None
                if dream is None or dream.status == "deleted":
                    error = "dream_deleted"
                elif job.status == "queued" and job.queued_at <= now-timedelta(
                    seconds=policy.queued_seconds
                ):
                    error = "queue_timeout"
                elif (job.status == "running"
                      and (job.lease_until is None or job.lease_until <= now)):
                    error = "interrupted"
                if error:
                    job.status, job.error_code, job.finished_at = "failed", error, now
                    job.claim_token = job.lease_until = None
                    meta = db.get(DreamEmotion, job.dream_id)
                    if meta and meta.active_request == job.id:
                        meta.active_request = None
                    db.commit()
                    report["failed"] += 1
            except SQLAlchemyError:
                db.rollback()
                report["deferred"] += 1
    return report
