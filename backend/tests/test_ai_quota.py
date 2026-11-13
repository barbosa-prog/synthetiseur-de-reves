"""Quota glissant sur PostgreSQL temporaire ; aucune inférence réelle."""

import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from backend.app.models import AIExecution, AIQuotaPolicy, Dream, ImageDescription, Job, Media
from backend.app.services import ai_quota, emotions, stt_jobs
from backend.app.services import job_lifecycle as lifecycle
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.dream_purge import DreamPurgeService
from backend.app.services.image_execution import run_once as image_once
from backend.app.services.job_maintenance import maintain
from backend.app.services.transcripts import apply_correction
from backend.app.web.security import SESSION_COOKIE
from backend.tests import test_job_lifecycle as cases
from backend.tests import test_job_routes_p11 as routes
from backend.tests.test_emotion_web import complete_fake
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_private_storage import wav_bytes
from backend.tests.test_stt import FakeProvider
from backend.tests.test_web import proof
from scripts import ai_quota as cli
from scripts.p11_inventory import capture

env = cases.env
client_env = routes.client_env


def limit(env, value):
    with env[2]() as db:
        lifecycle.bounded(db)
        ai_quota.configure(db, value)
        db.commit()


def count(env, owner=None):
    with env[2]() as db:
        return db.scalar(select(func.count()).select_from(AIExecution).where(
            AIExecution.user_id == (owner or env[3])))


def fill(env, size, *, times=None):
    with env[2]() as db:
        now = ai_quota.clock(db)
        for index in range(size):
            db.add(AIExecution(user_id=env[3], kind="emotion", attempt=1,
                reservation_token=uuid4(), admitted_at=times[index] if times else now))
        db.commit()


def new_job(env, kind="emotion", owner=None):
    owner = owner or env[3]
    with env[2]() as db:
        dream = Dream(user_id=owner, transcript="Ressenti fictif pour le quota.", text_version=1)
        db.add(dream)
        db.flush()
        identifier = dream.id
        if kind == "image":
            db.add(ImageDescription(dream_id=identifier, description="Foret fictive", version=1,
                                    text_version=1))
        db.commit()
    options = dict(text_version=1, engine=cases.identity(kind), parameters=cases.settings(kind),
                   explicit=True)
    if kind == "stt":
        media = env[7].store(owner, identifier, io.BytesIO(wav_bytes()),
                             kind="audio", media_format="wav")
        with env[2]() as db:
            db.get(Media, media).audio_source = "import"
            db.commit()
        options["media_id"] = media
    elif kind == "image":
        options["description_version"] = 1
    else:
        options["choice_revision"] = 0
    return lifecycle.create(env[2], owner, identifier, kind, **options)


def reserve(env, identifier, kind="emotion", owner=None, token=None):
    return lifecycle.reserve_job(env[2], owner or env[3], identifier,
                                 engine=cases.identity(kind), token=token or uuid4())


def test_twenty_executions_share_account_budget_across_kinds_and_dreams(env, monkeypatch):
    with env[2]() as db:
        now = ai_quota.clock(db)
    monkeypatch.setattr(ai_quota, "clock", lambda _: now)
    for index in range(20):
        kind = ["stt", "image", "emotion"][index % 3]
        identifier = new_job(env, kind)
        assert count(env) == index  # queued ne consomme rien
        reserve(env, identifier, kind)
    assert count(env) == 20
    with pytest.raises(HTTPException) as error:
        new_job(env)
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "86400", "Cache-Control": "no-store"}
    assert count(env) == 20


def test_concurrent_reservations_cannot_exceed_limit(env):
    limit(env, 4)
    identifiers = [new_job(env) for _ in range(12)]

    def attempt(identifier):
        try:
            reserve(env, identifier)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(attempt, identifiers))
    assert statuses.count(200) == 4 and statuses.count(429) == 8
    assert count(env) == 4
    with env[2]() as db:
        assert db.scalar(select(func.sum(Job.attempts))) == 4
        assert db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")) == 8


def test_two_accounts_have_independent_budgets_and_owner_checks(env):
    limit(env, 1)
    a, b = new_job(env), new_job(env, owner=env[4])
    with pytest.raises(HTTPException) as error:
        reserve(env, a, owner=env[4])
    assert error.value.status_code == 404 and count(env) == 0
    reserve(env, a)
    reserve(env, b, owner=env[4])
    assert count(env) == count(env, env[4]) == 1


def test_two_os_processes_share_the_last_unit(env):
    limit(env, 1)
    identifiers = [new_job(env), new_job(env)]
    url = env[0].url
    assert url.database in {"p07_validation", "p20_validation"} and url.port != 5434
    raw = url.render_as_string(hide_password=False)
    child_env = {**os.environ, "P12_TEMP_URL": raw, "DATABASE_URL": raw,
                 "TEST_DATABASE_URL": raw, "EMOTION_ENABLED": "0"}
    code = """
import os, sys
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.engine import make_url
from backend.app.database import make_engine, session_factory
from backend.app.services.job_lifecycle import reserve_job
from backend.tests.test_job_lifecycle import identity
from scripts.test_safety import validate_target, probe
validate_target(os.environ, make_url(os.environ['P12_TEMP_URL']))
probe(os.environ)
engine = make_engine(make_url(os.environ['P12_TEMP_URL']))
try:
    try:
        reserve_job(session_factory(engine), UUID(sys.argv[1]), UUID(sys.argv[2]),
                    engine=identity('emotion'), token=uuid4())
        print(200)
    except HTTPException as exc:
        print(exc.status_code)
finally:
    engine.dispose()
"""
    children = []
    try:
        for identifier in identifiers:
            children.append(subprocess.Popen([sys.executable, "-c", code,
                str(env[3]), str(identifier)], env=child_env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        statuses = []
        for child in children:
            output, _ = child.communicate(timeout=30)
            assert child.returncode == 0
            statuses.append(int(output))
        assert sorted(statuses) == [200, 429] and count(env) == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


def test_sliding_window_boundary_and_exact_retry_after(env, monkeypatch):
    limit(env, 1)
    with env[2]() as db:
        now = ai_quota.clock(db)
    fill(env, 3, times=[now-timedelta(days=2), now-timedelta(hours=24),
                        now-timedelta(hours=2)])
    monkeypatch.setattr(ai_quota, "clock", lambda _: now)
    with pytest.raises(HTTPException) as error:
        new_job(env)
    assert error.value.headers["Retry-After"] == "79200"
    monkeypatch.setattr(ai_quota, "clock", lambda _: now+timedelta(hours=22))
    reserve(env, new_job(env))
    assert count(env) == 4  # Les anciennes unités ne sont pas effacées pour simuler l'expiration.


def test_limit_reduction_waits_for_enough_units_to_expire(env, monkeypatch):
    with env[2]() as db:
        now = ai_quota.clock(db)
    fill(env, 3, times=[now-timedelta(hours=n) for n in [3, 2, 1]])
    limit(env, 2)
    monkeypatch.setattr(ai_quota, "clock", lambda _: now)
    with pytest.raises(HTTPException) as error:
        new_job(env)
    assert error.value.headers["Retry-After"] == "79200"


def test_window_is_twenty_four_hours_across_daylight_saving(env, monkeypatch):
    limit(env, 1)
    admitted = datetime(2026, 3, 28, 12, tzinfo=timezone.utc)
    now = datetime(2026, 3, 29, 11, 30, tzinfo=timezone.utc)
    fill(env, 1, times=[admitted])
    monkeypatch.setattr(ai_quota, "clock", lambda _: now)
    with env[2]() as db:
        db.execute(text("SET LOCAL TIME ZONE 'Europe/Paris'"))
        with pytest.raises(HTTPException) as error:
            ai_quota.check(db, env[3])
    assert error.value.status_code == 429 and error.value.headers["Retry-After"] == "1800"


def test_quota_clock_is_utc_even_with_different_server_zone(env):
    with env[2]() as db:
        db.execute(text("SET LOCAL TIME ZONE 'Europe/Paris'"))
        assert ai_quota.clock(db).utcoffset() == timedelta(0)


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_success_deduplication_is_free_even_when_quota_full(env, kind):
    identifier = cases.create(env, kind)
    if kind == "stt":
        assert stt_jobs.run_once(env[2], env[7], FakeProvider())
    elif kind == "image":
        assert image_once(env[2], env[7].storage, FakeEngine())
    else:
        assert complete_fake(env[2])
    assert count(env) == 1
    fill(env, 19)
    with env[2]() as db:
        version = db.get(Dream, env[5]).text_version
    assert cases.create(env, kind, text_version=version) == identifier
    assert count(env) == 20
    if kind == "image":
        with pytest.raises(HTTPException) as error:
            cases.create(env, kind, new_image=True)
        assert error.value.status_code == 429


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_retries_keep_both_p11_and_global_budgets(env, kind):
    identifier = cases.create(env, kind)
    for attempt in range(3):
        cases.reserve(env, identifier, kind)
        assert count(env) == attempt+1
        cases.fail(env, identifier)
        if attempt < 2:
            lifecycle.retry_job(env[2], env[3], identifier,
                                engine=cases.identity(kind), explicit=True)
            assert count(env) == attempt+1  # La relance queued n'est pas encore une exécution.
    with pytest.raises(HTTPException) as error:
        lifecycle.retry_job(env[2], env[3], identifier, engine=cases.identity(kind), explicit=True)
    assert error.value.status_code == 409 and count(env) == 3


def test_atomic_rollback_and_duplicate_token_never_double_charge(env, monkeypatch):
    identifier = new_job(env)
    original = ai_quota.admit

    def broken(*args):
        original(*args)
        raise SQLAlchemyError("FICTITIOUS_QUOTA_ERROR")

    monkeypatch.setattr(ai_quota, "admit", broken)
    with pytest.raises(HTTPException):
        reserve(env, identifier)
    assert count(env) == 0
    with env[2]() as db:
        assert db.get(Job, identifier).status == "queued" and db.get(Job, identifier).attempts == 0
    monkeypatch.setattr(ai_quota, "admit", original)
    token = reserve(env, identifier)
    with pytest.raises(HTTPException):
        reserve(env, identifier, token=token)
    assert count(env) == 1


def test_restart_interruption_and_purge_do_not_refund_admission(env):
    identifier = new_job(env)
    token = reserve(env, identifier)
    env[0].dispose()
    lifecycle.stop_reservation(env[2], identifier, token)
    with env[2]() as db:
        assert db.get(Job, identifier).status == "failed"
        dream_id = db.get(Job, identifier).dream_id
        delete_dream(db, env[3], dream_id)
    service = DreamPurgeService(env[7])
    assert service.purge_one(env[3], dream_id) == "purged"
    with env[2]() as db:
        execution = db.scalar(select(AIExecution))
        assert execution.job_id is None and execution.user_id == env[3]
        assert db.get(Job, identifier) is None
    limit(env, 1)
    with pytest.raises(HTTPException) as error:
        new_job(env)
    assert error.value.status_code == 429 and count(env) == 1


def test_unstarted_cancelled_and_expired_jobs_cost_nothing(env):
    first, second = new_job(env), new_job(env)
    with env[2]() as db:
        row = db.get(Job, first)
        row.queued_at = ai_quota.clock(db)-timedelta(hours=1)
        delete_dream(db, env[3], db.get(Job, second).dream_id)
    assert maintain(env[2], apply=True)["failed"] == 1
    assert count(env) == 0


def test_worker_skips_full_account_without_starting_provider(env):
    identifier = new_job(env, "stt")
    fill(env, 20)

    class Never:
        timeout = 30

        def transcribe(self, _):
            pytest.fail("Aucune execution admise")

    assert not stt_jobs.run_once(env[2], env[7], Never())
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "queued" and row.attempts == 0 and row.claim_token is None
    assert count(env) == 20


def test_full_accounts_do_not_starve_another_owner_behind_one_hundred_jobs(env):
    limit(env, 1)
    for _ in range(101):
        new_job(env)
    other_job = new_job(env, owner=env[4])
    fill(env, 1)
    identifier, _ = emotions.claim(env[2])
    assert identifier == other_job and count(env, env[4]) == 1 and count(env) == 1


def test_expired_running_job_keeps_unit_and_retry_charges_again(env):
    identifier = new_job(env)
    reserve(env, identifier)
    with env[2]() as db:
        db.get(Job, identifier).lease_until = ai_quota.clock(db)-timedelta(seconds=1)
        db.commit()
    assert maintain(env[2], apply=True)["failed"] == 1 and count(env) == 1
    lifecycle.retry_job(env[2], env[3], identifier, engine=cases.identity("emotion"), explicit=True)
    assert count(env) == 1
    reserve(env, identifier)
    assert count(env) == 2


def test_new_text_cycle_cannot_reset_global_budget(env):
    limit(env, 1)
    identifier = cases.create(env, "image")
    cases.reserve(env, identifier, "image")
    cases.fail(env, identifier)
    with env[2]() as db:
        dream = db.get(Dream, env[5])
        apply_correction(db, dream, "Une autre scene entierement fictive.", 1)
        description = db.get(ImageDescription, env[5])
        description.text_version = 2
        description.version = 2
        db.commit()
    with pytest.raises(HTTPException) as error:
        cases.create(env, "image", text_version=2, description_version=2)
    assert error.value.status_code == 429 and count(env) == 1


def test_publication_requires_the_exact_quota_reservation(env):
    identifier = cases.create(env, "image")
    with env[2]() as db:
        row = db.get(Job, identifier)
        row.status, row.attempts, row.claim_token = "running", 1, uuid4()
        row.lease_until = ai_quota.clock(db)+timedelta(minutes=5)
        db.commit()
    with env[2]() as db, pytest.raises(HTTPException) as error:
        lifecycle.publication_guard(db, db.get(Job, identifier))
    assert error.value.status_code == 409 and count(env) == 0


@pytest.mark.parametrize("value", [0, -1, 10001, True])
def test_invalid_configuration_is_rejected(env, value):
    with env[2]() as db, pytest.raises(ValueError):
        ai_quota.configure(db, value)
    with env[2]() as db:
        assert db.get(AIQuotaPolicy, 1).execution_limit == 20


def test_missing_policy_fails_closed_without_starting_job(env):
    identifier = new_job(env)
    with env[2]() as db:
        db.delete(db.get(AIQuotaPolicy, 1))
        db.commit()
    with pytest.raises(HTTPException) as error:
        reserve(env, identifier)
    assert error.value.status_code == 503 and count(env) == 0
    with env[2]() as db:
        assert db.get(Job, identifier).status == "queued"


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_unsupported_transaction_snapshot_fails_closed(env, isolation):
    with env[2]() as db:
        # isolation est une constante du test, jamais un paramètre de requête.
        db.execute(text("SET TRANSACTION ISOLATION LEVEL "+isolation))
        with pytest.raises(HTTPException) as error:
            ai_quota.check(db, env[3])
    assert error.value.status_code == 503 and count(env) == 0


@pytest.mark.parametrize("error", ["timeout", "safety_blocked", "insufficient_memory"])
def test_failed_admitted_provider_never_refunds(env, error):
    identifier = cases.create(env, "image")
    assert image_once(env[2], env[7].storage, FakeEngine(error=error))
    with env[2]() as db:
        assert db.get(Job, identifier).status == "failed"
    assert count(env) == 1


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
def test_http_retry_refusal_is_safe_and_preserves_counters(client_env, kind):
    bundle, env = client_env, client_env[0]
    identifier, _ = routes.fail(bundle, kind)
    fill(env, 19)
    view = routes.status(bundle, identifier, kind)
    endpoint = routes.endpoint(identifier, kind)+"/retry"
    for other, status in [(True, 404), (False, 429)]:
        response = bundle[1].post(endpoint, json=routes.payload(view),
                                  headers=routes.headers(bundle, other))
        assert response.status_code == status
        if status == 429:
            assert 1 <= int(response.headers["retry-after"]) <= 86400
            assert response.json()["error"]["code"] == "rate_limited"
    assert bundle[1].post(endpoint, json=routes.payload(view)).status_code == 401
    bundle[1].cookies.set(SESSION_COOKIE, bundle[2][0])
    page = bundle[1].get(f"/reves/{env[5]}/{routes.PAGES[kind]}")
    response = bundle[1].post(view["retry_url"], data={
        "csrf": proof(page), "expected": view["confirmation"], "confirmed": "yes",
    }, headers={"Origin": routes.ORIGIN}, follow_redirects=False)
    assert response.status_code == 429 and response.headers["retry-after"].isdigit()
    with env[2]() as db:
        row = db.get(Job, identifier)
        assert row.status == "failed" and row.retry_count == 0 and row.attempts == 1
    assert count(env) == 20


@pytest.mark.parametrize("field,value", [("attempt", 0), ("attempt", 4), ("kind", "tts")])
def test_database_constraints_refuse_invalid_units(env, field, value):
    with pytest.raises(IntegrityError), env[2]() as db:
        values = dict(user_id=env[3], kind="stt", attempt=1, reservation_token=uuid4())
        db.add(AIExecution(**{**values, field: value}))
        db.commit()
    assert count(env) == 0


def test_migration_preserves_history_and_refuses_budget_loss(env):
    engine, config = env[:2]
    # Historique P11 fictif, sans inventer des admissions passées.
    identifier = cases.create(env)
    with engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "0009")
        before = capture(c)
        command.upgrade(config, "0010")
        after = capture(c)
        assert {k: v for k, v in after["tables"].items() if not k.startswith("ai_")} == (
            before["tables"])
        assert after["tables"]["ai_executions"]["count"] == 0
        assert c.scalar(text("SELECT execution_limit FROM ai_quota_policy")) == 20
    cases.reserve(env, identifier)
    with pytest.raises(DBAPIError), engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "0009")
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0010"
    assert count(env) == 1


def test_interrupted_migration_is_transactional(env):
    engine, config = env[:2]
    with engine.begin() as c:
        config.attributes["connection"] = c
        command.downgrade(config, "0009")
        before = capture(c)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if "CREATE TABLE ai_executions" in statement:
            raise RuntimeError("Interruption fictive migration P12")

    event.listen(engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError), engine.begin() as c:
            config.attributes["connection"] = c
            command.upgrade(config, "0010")
    finally:
        event.remove(engine, "after_cursor_execute", fail)
    with engine.begin() as c:
        assert capture(c) == before
        config.attributes["connection"] = c
        command.upgrade(config, "0010")


@pytest.mark.parametrize("args", [[], ["--apply", "--limit", "10", "--confirm-database", "other"]])
def test_cli_never_uses_implicit_or_wrong_database(monkeypatch, capsys, args):
    monkeypatch.setattr(sys, "argv", ["quota", *args])
    if not args:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/fictitious")
    monkeypatch.setattr(cli, "make_engine", lambda *_: pytest.fail("Connexion interdite"))
    assert cli.main() == 1
    assert "postgresql" not in capsys.readouterr().out


def test_configuration_is_central_and_cli_requires_explicit_apply(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_engine", lambda _: env[0])
    monkeypatch.setattr(sys, "argv", ["quota", "--apply", "--limit", "7",
                                      "--confirm-database", env[0].url.database])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["execution_limit"] == 7
    with env[2]() as db:
        assert db.get(AIQuotaPolicy, 1).execution_limit == 7
