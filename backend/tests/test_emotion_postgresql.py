"""P08 sur PostgreSQL temporaire ; aucun modèle ni fichier personnel."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.app.database import session_factory
from backend.app.emotion_provider import EmotionRequest
from backend.app.history_schemas import HistoryQuery
from backend.app.models import AuthSession, Dream, DreamEmotion, EmotionAnalysis, Job, User
from backend.app.security import new_token, token_digest
from backend.app.services import emotions as service
from backend.app.services.history import list_dreams
from backend.app.services.transcripts import apply_correction
from backend.tests.test_authentication import application_for
from backend.tests.test_emotion_contract import FakeEmotionProvider

pytestmark = pytest.mark.integration
FAKE_CONFIG = dict(
    engine="fake",
    model_revision="1",
    tokenizer_revision="fixture-v1",
    parameters_revision="fixed-v1",
    hypotheses=["fiction"],
    seed=42,
)


@pytest.fixture
def env(database):
    engine, config = database
    sessions = session_factory(engine)
    tokens = [new_token(), new_token()]
    with sessions() as db:
        users = [User(email=f"emotion-fiction-{i}@example.com") for i in range(2)]
        db.add_all(users)
        db.flush()
        for user, token in zip(users, tokens):
            db.add(
                AuthSession(
                    user_id=user.id,
                    token_hash=token_digest(token),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
        dream = Dream(user_id=users[0].id, transcript="Un récit fictif à corriger.", text_version=1)
        db.add(dream)
        db.commit()
        ids = users[0].id, users[1].id, dream.id
    with TestClient(application_for(engine)) as client:
        yield engine, config, sessions, ids, tokens, client


def queue(env, revision=0, version=1):
    _, _, sessions, (owner, _, dream), _, _ = env
    with sessions() as db:
        return service.enqueue(db, owner, dream, version, revision, parameters=FAKE_CONFIG)["id"]


def output(env, job_id, emotion="heureux", reason=None):
    with env[2]() as db:
        row = db.get(EmotionAnalysis, job_id)
        request = EmotionRequest(
            request_id=job_id,
            text=row.transcript,
            text_version=row.text_version,
            choice_revision=row.choice_revision,
        )
        return FakeEmotionProvider(emotion, reason).analyze(request)


def headers(env, account=0):
    return {"Authorization": "Bearer " + env[4][account]}


def test_suggestion_is_separate_acceptance_persists_and_feeds_history(env):
    identifier = queue(env)
    assert service.run_once(env[2], FakeEmotionProvider())
    engine, _, sessions, (owner, _, dream), _, _ = env
    engine.dispose()
    with sessions() as db:
        state = service.projection(db, owner, dream)
        assert state["value"] is None and state["suggestion"]["emotion"] == "heureux"
        assert db.get(EmotionAnalysis, identifier).parameters == FAKE_CONFIG
        assert list_dreams(db, owner, HistoryQuery(emotion="non_renseignee")).total == 1
        state = service.accept(db, owner, dream, identifier, state["revision"])
        assert state["source"] == "accepted" and state["value"] == "heureux"
        assert list_dreams(db, owner, HistoryQuery(emotion="heureux")).total == 1
        assert db.get(Dream, dream).transcript == "Un récit fictif à corriger."


@pytest.mark.parametrize("value", ["heureux", "triste", None])
def test_manual_change_inflight_blocks_late_result_and_future_auto_assignment(env, value):
    identifier = queue(env)
    reservation = service.claim(env[2])
    result = output(env, identifier)
    with env[2]() as db:
        state = service.correct(db, env[3][0], env[3][2], value, 1)
        revision = state["revision"]
    assert not service.finish(env[2], *reservation, result)
    queue(env, revision=revision)
    assert service.run_once(env[2], FakeEmotionProvider("autre"))
    with env[2]() as db:
        state = service.projection(db, env[3][0], env[3][2])
        assert state["value"] == value
        assert state["source"] == ("manual" if value else "withdrawn")


@pytest.mark.parametrize("accepted", [False, True])
def test_p06_invalidates_suggestion_preserves_explicit_choice(env, accepted):
    identifier = queue(env)
    service.run_once(env[2], FakeEmotionProvider())
    with env[2]() as db:
        state = service.projection(db, env[3][0], env[3][2])
        if accepted:
            service.accept(db, env[3][0], env[3][2], identifier, state["revision"])
        else:
            service.correct(db, env[3][0], env[3][2], "triste", state["revision"])
        dream = db.get(Dream, env[3][2], with_for_update=True)
        apply_correction(db, dream, "Une nouvelle fiction.", 1)
        db.commit()
        state = service.projection(db, env[3][0], env[3][2])
        assert state["suggestion"] is None and state["selected_text_version"] == 1
        assert state["value"] == ("heureux" if accepted else "triste")
        assert db.get(EmotionAnalysis, identifier).result is not None
        with pytest.raises(HTTPException):
            service.accept(db, env[3][0], env[3][2], identifier, state["revision"])


def test_p06_during_calculation_and_duplicate_publication(env):
    identifier = queue(env)
    reservation = service.claim(env[2])
    result = output(env, identifier)
    with env[2]() as db:
        dream = db.get(Dream, env[3][2], with_for_update=True)
        apply_correction(db, dream, "Correction fictive pendant calcul.", 1)
        db.commit()
    assert not service.finish(env[2], *reservation, result)
    with env[2]() as db:
        assert db.get(Job, identifier).error_code == "stale_result"
    identifier = queue(env, revision=2, version=2)
    reservation = service.claim(env[2])
    result = output(env, identifier)
    assert service.finish(env[2], *reservation, result)
    assert not service.finish(env[2], *reservation, result)


def test_abstention_cannot_be_accepted(env):
    identifier = queue(env)
    service.run_once(env[2], FakeEmotionProvider(None, "ambiguous"))
    with env[2]() as db:
        state = service.projection(db, env[3][0], env[3][2])
        assert state["value"] is None and state["suggestion"]["abstention_reason"] == "ambiguous"
        with pytest.raises(HTTPException):
            service.accept(db, env[3][0], env[3][2], identifier, state["revision"])


@pytest.mark.parametrize("error", ["timeout", "worker_stopped", "PRIVATE_PROVIDER_DETAIL"])
def test_errors_and_recovery_of_manual_path(env, error):
    identifier = queue(env)
    reservation = service.claim(env[2])
    assert not service.finish(env[2], *reservation, error=error)
    with env[2]() as db:
        assert db.get(Job, identifier).error_code in {
            "timeout",
            "worker_stopped",
            "provider_failed",
        }
        revision = service.projection(db, env[3][0], env[3][2])["revision"]
        assert service.correct(db, env[3][0], env[3][2], "autre", revision)["value"] == "autre"


def test_provider_exception_and_wrong_snapshot_output(env):
    class Broken:
        def analyze(self, request):
            raise RuntimeError("PRIVATE")

    identifier = queue(env)
    service.run_once(env[2], Broken())
    with env[2]() as db:
        assert db.get(Job, identifier).error_code == "provider_failed"
    identifier = queue(env, revision=1)
    reservation = service.claim(env[2])
    forged = output(env, identifier).model_copy(update={"model_revision": "wrong"})
    assert not service.finish(env[2], *reservation, forged)


def test_lease_recovery_expiry_and_old_token(env):
    identifier = queue(env)
    first = service.claim(env[2])
    assert service.claim(env[2]) is None
    result = output(env, identifier)
    for attempt in range(2, 4):
        with env[2]() as db:
            job = db.get(Job, identifier)
            job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        assert not service.finish(env[2], *first, result)
        new = service.claim(env[2])
        assert new[0] == identifier and new[1] != first[1]
        assert not service.finish(env[2], *first, result)
        with env[2]() as db:
            assert db.get(Job, identifier).attempts == attempt
        first = new
    with env[2]() as db:
        db.get(Job, identifier).lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert service.claim(env[2]) is None
    with env[2]() as db:
        assert db.get(Job, identifier).error_code == "interrupted"


def test_concurrent_requests_and_claims(env):
    def request(_):
        try:
            return queue(env)
        except HTTPException as exc:
            assert exc.status_code == 409
            return None

    with ThreadPoolExecutor(2) as pool:
        assert sum(r is not None for r in pool.map(request, range(2))) == 1
    with ThreadPoolExecutor(2) as pool:
        assert sum(r is not None for r in pool.map(lambda _: service.claim(env[2]), range(2))) == 1


@pytest.mark.parametrize("operation", ["read", "correct", "request", "status", "accept", "cancel"])
def test_api_permissions_and_anonymous(env, operation):
    identifier = queue(env)
    client = env[5]
    base = f"/api/v1/dreams/{env[3][2]}/emotion"
    method, path, body = {
        "read": ("GET", base, None),
        "correct": ("PUT", base, dict(emotion="triste", expected_revision=1)),
        "request": (
            "POST",
            base + "/suggestions",
            dict(expected_text_version=1, expected_revision=1),
        ),
        "status": ("GET", f"/api/v1/emotion-jobs/{identifier}", None),
        "cancel": ("DELETE", f"/api/v1/emotion-jobs/{identifier}", None),
        "accept": (
            "POST",
            base + "/accept",
            dict(suggestion_id=str(identifier), expected_revision=1),
        ),
    }[operation]
    assert client.request(method, path, json=body).status_code == 401
    assert client.request(method, path, json=body, headers=headers(env, 1)).status_code == 404


def test_api_validation_status_legacy_patch_and_cookie_cannot_authenticate(env):
    client, dream = env[5], env[3][2]
    base = f"/api/v1/dreams/{dream}/emotion"
    assert client.get(base, headers=headers(env)).json()["revision"] == 0
    assert client.patch(f"/api/v1/dreams/{dream}", headers=headers(env),
                        json=dict(emotion="heureux")).status_code == 409
    assert (
        client.put(
            base, json=dict(emotion="invalid", expected_revision=0), headers=headers(env)
        ).status_code
        == 422
    )
    assert (
        client.put(
            base, json=dict(emotion="heureux", expected_revision=9), headers=headers(env)
        ).status_code
        == 409
    )
    response = client.post(
        base + "/suggestions",
        headers=headers(env),
        json=dict(expected_text_version=1, expected_revision=0),
    )
    assert response.status_code == 202
    assert (
        client.get(f"/api/v1/emotion-jobs/{response.json()['id']}", headers=headers(env)).headers[
            "cache-control"
        ]
        == "no-store"
    )
    patch = client.patch(
        f"/api/v1/dreams/{dream}",
        headers=headers(env),
        json=dict(
            transcript="Fiction modifiée et choix explicite.",
            expected_text_version=1,
            emotion="neutre",
            expected_emotion_revision=1,
        ),
    )
    assert patch.status_code == 200
    state = client.get(base, headers=headers(env)).json()
    assert state["source"] == "manual" and state["value"] == "neutre"
    assert state["suggestion"] is None and state["text_version"] == 2
    assert (
        client.get(base.replace(str(dream), str(uuid4())), headers=headers(env)).status_code == 404
    )
    client.cookies.set("session", env[4][0])
    assert client.get(base).status_code == 401
    client.cookies.clear()
    assert "transcript" not in state and "claim_token" not in state


def test_database_uniqueness_and_snapshot_constraints(env):
    identifier = queue(env)
    with env[2]() as db, pytest.raises(IntegrityError):
        db.add(Job(dream_id=env[3][2], kind="emotion"))
        db.commit()
    with env[2]() as db, pytest.raises(IntegrityError):
        db.get(EmotionAnalysis, identifier).text_version = 0
        db.commit()


def test_cancel_releases_slot_and_old_result_cannot_publish(env):
    identifier = queue(env)
    reservation = service.claim(env[2])
    result = output(env, identifier)
    response = env[5].delete(f"/api/v1/emotion-jobs/{identifier}", headers=headers(env))
    assert response.status_code == 204
    assert not service.finish(env[2], *reservation, result)
    with env[2]() as db:
        assert service.job_projection(db, env[3][0], identifier)["error_code"] == "cancelled"
    assert queue(env, revision=1) != identifier


def test_acceptance_api_and_no_implicit_reclassification(env):
    identifier = queue(env)
    service.run_once(env[2], FakeEmotionProvider("autre"))
    client = env[5]
    endpoint = f"/api/v1/dreams/{env[3][2]}/emotion"
    view = client.get(endpoint, headers=headers(env)).json()
    assert view["value"] is None and view["revision"] == 2
    response = client.post(
        endpoint + "/accept",
        headers=headers(env),
        json=dict(suggestion_id=str(identifier), expected_revision=2),
    )
    assert response.status_code == 200
    assert response.json()["value"] == "autre" and response.json()["source"] == "accepted"
    assert (
        client.post(
            endpoint + "/accept",
            headers=headers(env),
            json=dict(suggestion_id=str(identifier), expected_revision=2),
        ).status_code
        == 409
    )


def test_running_job_status_marks_obsolete_choice_and_owner_change_refused(env):
    identifier = queue(env)
    reservation = service.claim(env[2])
    result = output(env, identifier)
    with env[2]() as db:
        service.correct(db, env[3][0], env[3][2], "triste", 1)
        assert service.job_projection(db, env[3][0], identifier)["stale"]
    assert not service.finish(env[2], *reservation, result)
    with env[2]() as db:
        service.enqueue(db, env[3][0], env[3][2], 1, 2, parameters=FAKE_CONFIG)
    reservation = service.claim(env[2])
    result = output(env, reservation[0])
    with env[2]() as db:
        db.get(Dream, env[3][2]).user_id = env[3][1]
        db.commit()
    assert not service.finish(env[2], *reservation, result)
def test_migration_0007_0008_legacy_and_safe_downgrade(database):
    engine, config = database
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007")
        owner = connection.scalar(text("INSERT INTO users DEFAULT VALUES RETURNING id"))
        dream = connection.scalar(
            text("INSERT INTO dreams(user_id,emotion) VALUES (:u,'triste') RETURNING id"),
            {"u": owner},
        )
        command.upgrade(config, "0008")
        assert (
            connection.scalar(text("SELECT emotion FROM dreams WHERE id=:id"), {"id": dream})
            == "triste"
        )
        row = connection.execute(
            text("SELECT source,selected_text_version FROM dream_emotions WHERE dream_id=:id"),
            {"id": dream},
        ).one()
        assert row == ("legacy", None)
        command.downgrade(config, "0007")
        command.upgrade(config, "0008")
    sessions = session_factory(engine)
    with sessions() as db:
        db.add(Job(dream_id=dream, kind="emotion"))
        db.commit()
    with pytest.raises(DBAPIError), engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007")
    with sessions() as db:
        assert db.get(Dream, dream).emotion == "triste"
        assert (
            db.scalar(select(DreamEmotion.source).where(DreamEmotion.dream_id == dream)) == "legacy"
        )
        # Fixture temporaire uniquement : vérifie aussi la garde sans aucun job.
        db.query(Job).filter(Job.kind == "emotion").delete()
        db.get(DreamEmotion, dream).revision = 1
        db.commit()
    with pytest.raises(DBAPIError), engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007")
