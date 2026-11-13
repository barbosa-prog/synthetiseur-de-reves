"""P11 raccordé : PostgreSQL temporaire, fichiers synthétiques et fournisseurs factices."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.app.models import Dream, DreamEmotion, Job
from backend.app.services import emotions, image_jobs, stt_jobs
from backend.app.services import image_execution as images
from backend.app.services import job_lifecycle as lifecycle
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.transcripts import apply_correction
from backend.tests import test_job_lifecycle as cases
from backend.tests.browser_workers import wait_for_work
from backend.tests.test_emotion_contract import FakeEmotionProvider
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_stt import FakeProvider

env = cases.env
settings = cases.settings


def queue(env, kind):
    with env[2]() as db:
        if kind == "stt":
            return stt_jobs.enqueue(db, env[3], env[5], env[6],
                                    db.get(Dream, env[5]).text_version).id
        if kind == "image":
            return image_jobs.enqueue(db, env[3], env[5], 1, 1).id
        meta = db.get(DreamEmotion, env[5])
        return emotions.enqueue(db, env[3], env[5], 1, meta.revision if meta else 0,
                                parameters=settings("emotion"))["id"]


def execute(env, kind, provider=None):
    if kind == "stt":
        return stt_jobs.run_once(env[2], env[7], provider or FakeProvider())
    if kind == "image":
        return images.run_once(env[2], env[7].storage, provider or FakeEngine())
    return emotions.run_once(env[2], provider or FakeEmotionProvider(), timeout=120)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_connected_cycles_and_success_dedup(env, kind):
    identifier = queue(env, kind)
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "queued" and row.cycle_key and row.attempts == 0
    assert execute(env, kind)
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "done" and row.attempts == 1
        assert row.claim_token is row.lease_until is None
        assert db.get(Dream, env[5]).emotion is None
        if kind == "stt":
            assert row.input_snapshot["_output"]["text_version"] == 2
        if kind == "image":
            assert image_jobs.enqueue(db, env[3], env[5], 1, 1,
                                      media_service=env[7]).id == identifier
        else:
            assert queue(env, kind) == identifier
    assert not execute(env, kind)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_connected_failures_require_explicit_bounded_retries(env, kind):
    identifier = queue(env, kind)

    class Failure:
        timeout = 120

        def transcribe(self, _):
            from backend.app.stt_provider import STTError
            raise STTError("timeout")

        def generate(self, _):
            from backend.app.image_provider import ImageError
            raise ImageError("timeout")

        def analyze(self, _):
            from backend.app.emotion_provider import EmotionError
            raise EmotionError("timeout")

    for attempt in range(1, 4):
        assert execute(env, kind, Failure())
        assert not execute(env, kind, Failure())
        with env[2]() as db:
            row = db.get(Job, identifier)
            approved = lifecycle.read_inputs(row.input_snapshot).engine
            assert row.status == "failed" and row.attempts == attempt
        with pytest.raises(HTTPException):
            queue(env, kind)
        if attempt < 3:
            lifecycle.retry_job(env[2], env[3], identifier, engine=approved, explicit=True)
    with pytest.raises(HTTPException):
        lifecycle.retry_job(env[2], env[3], identifier, engine=approved, explicit=True)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_restart_expired_jobs_never_execute_automatically(env, kind):
    identifier = queue(env, kind)
    reservation = lifecycle.claim_next(env[2], kind, 120)
    with env[2]() as db:
        db.get(Job, identifier).lease_until = datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    env[0].dispose()
    assert lifecycle.claim_next(env[2], kind, 120) is None
    assert reservation[0] == identifier
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "failed" and row.attempts == 1
        assert row.error_code == "interrupted" and row.claim_token is None


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_two_consumers_only_reserve_once(env, kind):
    queue(env, kind)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: lifecycle.claim_next(env[2], kind, 120), [1, 2]))
    assert sum(item is not None for item in results) == 1


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_unidentified_history_is_never_adopted_or_executed(env, kind):
    with env[2]() as db:
        row = Job(dream_id=env[5], kind=kind)
        db.add(row)
        db.commit()
        identifier = row.id
    assert not execute(env, kind)
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "failed" and row.error_code == "configuration"
        assert row.cycle_key is None and row.attempts == 0
    with pytest.raises(HTTPException):
        queue(env, kind)


def test_whisper_1800_second_timeout_sets_1920_second_lease(env):
    identifier = queue(env, "stt")
    assert stt_jobs.claim(env[2], 1800)
    with env[2]() as db:
        row = db.get(Job, identifier)
        seconds = (row.lease_until-db.scalar(select(func.clock_timestamp()))).total_seconds()
        assert 1910 < seconds <= 1920


def test_stt_late_correction_and_controlled_interrupt(env):
    identifier = queue(env, "stt")

    def correct():
        with env[2]() as db:
            apply_correction(db, db.get(Dream, env[5]), "Correction fictive P11", 1)
            db.commit()

    assert execute(env, "stt", FakeProvider(callback=correct))
    with env[2]() as db:
        assert db.get(Job, identifier).status == "failed"
        assert db.get(Dream, env[5]).transcript == "Correction fictive P11"


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_ctrl_c_releases_reservation_without_new_attempt(env, kind):
    identifier = queue(env, kind)

    class Stop:
        timeout = 120

        def transcribe(self, _):
            raise KeyboardInterrupt

        generate = transcribe
        analyze = transcribe

    with pytest.raises(KeyboardInterrupt):
        execute(env, kind, Stop())
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "failed" and row.error_code == "worker_stopped"
        assert row.attempts == 1 and row.claim_token is None
    assert not execute(env, kind)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_database_unavailable_never_calls_provider(kind):
    def unavailable():
        raise OperationalError("fiction", None, Exception("private detail"))

    class Never:
        timeout = 120

        def transcribe(self, _):
            pytest.fail("Aucune IA autorisée")

    with pytest.raises(OperationalError):
        if kind == "stt":
            stt_jobs.run_once(unavailable, None, Never())
        elif kind == "image":
            images.run_once(unavailable, None, Never())
        else:
            emotions.run_once(unavailable, Never())


def test_deletion_during_image_calculation_blocks_publication(env):
    identifier = queue(env, "image")

    def remove():
        with env[2]() as db:
            delete_dream(db, env[3], env[5])

    assert execute(env, "image", FakeEngine(callback=remove))
    with env[2]() as db:
        assert db.get(Job, identifier).status == "failed"
        assert db.scalar(select(Job.media_id).where(Job.id == identifier)) is None


def test_image_voluntary_generation_shares_budget(env):
    first = queue(env, "image")
    assert execute(env, "image")
    with env[2]() as db:
        second = image_jobs.enqueue(db, env[3], env[5], 1, 1, new_generation=True).id
        assert second != first
    assert execute(env, "image")
    with env[2]() as db:
        image_jobs.enqueue(db, env[3], env[5], 1, 1, new_generation=True)
    assert execute(env, "image")
    with env[2]() as db, pytest.raises(HTTPException):
        image_jobs.enqueue(db, env[3], env[5], 1, 1, new_generation=True)


@pytest.mark.parametrize("kind", ["image", "emotion"])
def test_qualified_image_and_emotion_timeout_has_margin(env, kind):
    identifier = queue(env, kind)
    assert lifecycle.claim_next(env[2], kind, 120)
    with env[2]() as db:
        row = db.get(Job, identifier)
        seconds = (row.lease_until-db.scalar(select(func.clock_timestamp()))).total_seconds()
        assert 230 < seconds <= 240


def test_emotion_abstention_preserves_manual_choice(env):
    with env[2]() as db:
        emotions.correct(db, env[3], env[5], "triste", 0)
    identifier = queue(env, "emotion")
    assert execute(env, "emotion", FakeEmotionProvider(None, "ambiguous"))
    with env[2]() as db:
        assert db.get(Dream, env[5]).emotion == "triste"
        assert db.get(Job, identifier).status == "done"


def test_worker_honors_configured_queue_deadline(env, monkeypatch):
    monkeypatch.setenv("P11_QUEUE_TIMEOUT_SECONDS", "3600")
    identifier = queue(env, "stt")
    with env[2]() as db:
        db.get(Job, identifier).queued_at = db.scalar(select(func.clock_timestamp()))-timedelta(
            minutes=31)
        db.commit()
    assert stt_jobs.claim(env[2], 600)[0] == identifier


def test_bad_stt_manifest_remains_unverified(tmp_path):
    from backend.app.job_config import stt_parameters
    from backend.app.stt_provider import STTConfig
    (tmp_path / "download-complete.json").write_text("[]", encoding="utf-8")
    config = STTConfig("faster-whisper", tmp_path)
    assert stt_parameters(config)["model_revision"] == "local-unverified"


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_dream_lock_contention_defers_without_failing_valid_job(env, kind):
    identifier = queue(env, kind)
    with env[2]() as blocker:
        if kind == "emotion":
            # Le GET /emotion/statut prend exactement ce verrou via projection().
            emotions.projection(blocker, env[3], env[5])
        else:
            blocker.scalar(select(Dream).where(Dream.id == env[5]).with_for_update())
        assert lifecycle.claim_next(env[2], kind, 600) is None
        blocker.rollback()
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "queued" and row.attempts == 0
    assert lifecycle.claim_next(env[2], kind, 600)[0] == identifier


def test_fake_emotion_worker_retries_reservation_deferred_by_status_poll(env):
    identifier = queue(env, "emotion")
    reservations = []
    with env[2]() as polling:
        emotions.projection(polling, env[3], env[5])

        def reserve():
            reservation = emotions.claim(env[2])
            reservations.append(reservation)
            if reservation is None:
                with env[2]() as db:
                    job = db.get(Job, identifier)
                    assert job.status == "queued" and job.attempts == 0
                # Fin du GET de suivi : la prochaine itération peut réserver.
                polling.rollback()
            return reservation

        reservation = wait_for_work(reserve)
    assert reservations == [None, reservation]
    assert reservation[0] == identifier
    with env[2]() as db:
        job = db.get(Job, identifier)
        assert job.status == "running" and job.attempts == 1
