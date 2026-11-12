"""Worker et adaptateur : faux moteur seulement, aucune dépendance IA."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.app.emotion_config import enabled, parameters
from backend.app.emotion_provider import EmotionError, EmotionRequest, LocalMDeberta, analyze
from backend.app.emotion_runner import worker_slot
from backend.app.emotion_worker import heavy_jobs_running, main, work_once
from backend.app.models import Dream, Job
from backend.tests import test_emotion_postgresql as cases
from backend.tests.test_emotion_contract import FakeEmotionProvider
from backend.tests.test_emotion_postgresql import FAKE_CONFIG, queue
from scripts.emotion_cpu_bridge import stop_reason

env = cases.env


def test_disabled_worker_never_opens_database(monkeypatch):
    monkeypatch.delenv("EMOTION_ENABLED", raising=False)
    monkeypatch.setattr("sys.argv", ["emotion_worker", "--once"])
    monkeypatch.setattr("backend.app.database.make_engine", lambda: pytest.fail("DB access"))
    assert not enabled() and main() == 0


def test_enabled_cli_requires_explicit_database_url(monkeypatch):
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["emotion_worker", "--once"])
    monkeypatch.setattr("backend.app.database.make_engine", lambda: pytest.fail("DB access"))
    assert main() == 1


def test_adapter_disabled_and_metadata_validation():
    class Runner:
        def run(self, request, config):
            return FakeEmotionProvider().analyze(request).model_dump(mode="json")

    request = EmotionRequest(request_id=uuid4(), text="Fiction.", text_version=1, choice_revision=0)
    with pytest.raises(EmotionError, match="disabled"):
        LocalMDeberta(Runner(), dict(inference_enabled=False)).analyze(request)
    config = dict(inference_enabled=True, **FAKE_CONFIG)
    assert analyze(LocalMDeberta(Runner(), config), request).emotion == "heureux"
    with pytest.raises(EmotionError, match="invalid_result"):
        LocalMDeberta(Runner(), {**config, "model_revision": "wrong"}).analyze(request)


@pytest.mark.parametrize(
    "available,private,elapsed,expected",
    [
        (1500, 1000, 1, "insufficient_memory"),
        (2000, 4000, 1, "insufficient_memory"),
        (2000, 1000, 121, "timeout"),
        (2000, 1000, 1, None),
    ],
)
def test_monitor_limits(available, private, elapsed, expected):
    assert stop_reason(available, private, elapsed, parameters()) == expected


def test_windows_single_worker_slot(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.app.emotion_runner.local_root", lambda: tmp_path)
    with worker_slot() as first:
        assert first
        with worker_slot() as second:
            assert not second
    with worker_slot() as third:
        assert third


def test_snapshot_mismatch_does_not_call_provider(env):
    queue(env)

    class Never:
        def analyze(self, request):
            pytest.fail("No model should be called")

    assert work_once(env[2], Never(), parameters())
    with env[2]() as db:
        assert db.query(Job).filter(Job.kind == "emotion").one().error_code == "configuration"


def test_other_heavy_worker_defers_reservation(env):
    identifier = queue(env)
    with env[2]() as db:
        db.add(
            Job(
                dream_id=env[3][2],
                kind="stt",
                status="running",
                lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
        db.commit()
    assert heavy_jobs_running(env[2])
    assert not work_once(env[2], FakeEmotionProvider(), FAKE_CONFIG)
    with env[2]() as db:
        assert db.get(Job, identifier).attempts == 0


def test_worker_never_emits_update_to_dream_table(env):
    identifier = queue(env)
    statements = []

    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement.lower())

    event.listen(env[0], "before_cursor_execute", capture)
    try:
        assert work_once(env[2], FakeEmotionProvider(), FAKE_CONFIG)
    finally:
        event.remove(env[0], "before_cursor_execute", capture)
    assert not any(statement.startswith("update dreams ") for statement in statements)
    with env[2]() as db:
        assert db.get(Dream, env[3][2]).emotion is None
        assert db.get(Job, identifier).status == "done"


@pytest.mark.parametrize("code", ["timeout", "model_unavailable", "insufficient_memory"])
def test_adapter_errors_stay_technical_and_no_emotion(env, code):
    queue(env)

    class Broken:
        def analyze(self, request):
            raise EmotionError(code)

    work_once(env[2], Broken(), FAKE_CONFIG)
    with env[2]() as db:
        assert db.get(Dream, env[3][2]).emotion is None
        assert db.query(Job).filter(Job.kind == "emotion").one().error_code == code


def test_interrupted_worker_marks_failure_and_releases_reservation(env):
    identifier = queue(env)

    class Interrupted:
        def analyze(self, request):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        work_once(env[2], Interrupted(), FAKE_CONFIG)
    with env[2]() as db:
        job = db.get(Job, identifier)
        assert job.error_code == "worker_stopped" and job.claim_token is None


def test_parameters_are_serializable_and_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EMOTION_ENABLED", raising=False)
    assert json.loads(json.dumps(parameters()))["inference_enabled"] is False
