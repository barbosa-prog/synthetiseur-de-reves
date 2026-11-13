"""Relances publiques P11 : PostgreSQL temporaire, comptes et fournisseurs fictifs."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.emotion_provider import EmotionError
from backend.app.models import (
    AuthSession,
    Dream,
    DreamEmotion,
    ImageDescription,
    ImageGeneration,
    Job,
)
from backend.app.security import new_token, token_digest
from backend.app.services import job_tracking
from backend.app.services.dream_deletion import delete_dream
from backend.app.services.transcripts import apply_correction
from backend.app.web.security import SESSION_COOKIE
from backend.tests import test_worker_jobs_p11 as cases
from backend.tests.test_authentication import application_for
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_stt import FakeProvider
from backend.tests.test_web import proof

env = cases.env
ORIGIN = "https://localhost:8443"
PREFIXES = {"stt": "transcriptions", "image": "images", "emotion": "emotion-jobs"}
PAGES = {"stt": "transcription", "image": "image", "emotion": "emotion"}


@pytest.fixture
def client_env(env, monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    monkeypatch.setattr(job_tracking, "emotion_parameters", lambda: cases.settings("emotion"))
    tokens = [new_token(), new_token()]
    with env[2]() as db:
        for owner, token in zip([env[3], env[4]], tokens):
            db.add(AuthSession(user_id=owner, token_hash=token_digest(token),
                expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
        db.commit()
    app = application_for(env[0])
    app.state.media_storage = env[7].storage
    with TestClient(app, base_url=ORIGIN) as client:
        yield env, client, tokens


def headers(bundle, other=False):
    return {"Authorization": "Bearer " + bundle[2][int(other)]}


def endpoint(identifier, kind):
    return f"/api/v1/{PREFIXES[kind]}/{identifier}"


def status(bundle, identifier, kind):
    return bundle[1].get(endpoint(identifier, kind), headers=headers(bundle)).json()["tracking"]


def payload(view, **changes):
    return {**dict(confirmed=True, expected_text_version=view["text_version"],
        expected_retry_count=view["retry_count"],
        expected_description_version=view["description_version"],
        expected_choice_revision=view["choice_revision"]), **changes}


def fail(bundle, kind):
    env = bundle[0]
    identifier = cases.queue(env, kind)

    class Failure:
        def analyze(self, _):
            raise EmotionError("timeout")

    provider = {"stt": FakeProvider(error="timeout"), "image": FakeEngine(error="timeout"),
                "emotion": Failure()}[kind]
    assert cases.execute(env, kind, provider)
    return identifier, provider


@pytest.mark.parametrize("kind", PREFIXES)
def test_api_retry_budget_and_stale_duplicate_confirmation(client_env, kind):
    bundle = client_env
    identifier, provider = fail(bundle, kind)
    route = endpoint(identifier, kind) + "/retry"
    for retry in range(2):
        view = status(bundle, identifier, kind)
        assert view["technical_state"] == "failed" and view["retryable"]
        assert (view["cycle_attempts"], view["retry_count"], view["retries_remaining"]) == (
            retry+1, retry, 2-retry)
        body = payload(view)
        response = bundle[1].post(route, json=body, headers=headers(bundle))
        assert response.status_code == 202 and response.json()["tracking"]["technical_state"] == (
            "queued")
        assert cases.execute(bundle[0], kind, provider)
        assert bundle[1].post(route, json=body, headers=headers(bundle)).status_code == 409
    view = status(bundle, identifier, kind)
    assert not view["retryable"] and view["retries_remaining"] == 0
    assert view["cycle_attempts"] == 3
    assert bundle[1].post(route, json=payload(view), headers=headers(bundle)).status_code == 409


@pytest.mark.parametrize("kind", PREFIXES)
def test_api_auth_owner_confirmation_and_get_never_retries(client_env, kind):
    bundle = client_env
    identifier, _ = fail(bundle, kind)
    route = endpoint(identifier, kind) + "/retry"
    body = payload(status(bundle, identifier, kind))
    assert bundle[1].post(route, json=body).status_code == 401
    assert bundle[1].post(route, json=body,
                          headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert bundle[1].post(route, json=body, headers=headers(bundle, True)).status_code == 404
    assert bundle[1].get(route, headers=headers(bundle)).status_code == 405
    assert bundle[1].post(route, json={**body, "confirmed": False},
                          headers=headers(bundle)).status_code == 409
    assert bundle[1].post(route, json={**body, "confirmed": "yes"},
                          headers=headers(bundle)).status_code == 422
    assert bundle[1].post(route.replace(str(identifier), str(uuid4())), json=body,
                          headers=headers(bundle)).status_code == 404
    assert status(bundle, identifier, kind)["retry_count"] == 0


@pytest.mark.parametrize("kind", PREFIXES)
def test_two_retry_requests_only_consume_once(client_env, kind):
    bundle = client_env
    identifier, _ = fail(bundle, kind)
    body = payload(status(bundle, identifier, kind))
    route = endpoint(identifier, kind) + "/retry"
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(lambda _: bundle[1].post(route, json=body,
                            headers=headers(bundle)).status_code, [1, 2]))
    assert sorted(codes) == [202, 409]
    assert status(bundle, identifier, kind)["retry_count"] == 1


@pytest.mark.parametrize("kind", PREFIXES)
def test_web_confirmation_csrf_and_session_are_required(client_env, kind):
    bundle = client_env
    identifier, _ = fail(bundle, kind)
    env, client, tokens = bundle
    stage = f"/reves/{env[5]}/{PAGES[kind]}"
    route = f"/reves/{env[5]}/traitements/{kind}/{identifier}/relancer"
    assert client.post(route, data={}, follow_redirects=False).status_code == 303
    client.cookies.set(SESSION_COOKIE, tokens[1])
    assert client.get(stage).status_code == 404
    client.cookies.set(SESSION_COOKIE, tokens[0])
    page = client.get(stage)
    assert page.status_code == 200 and "Relancer le traitement" in page.text
    view = status(bundle, identifier, kind)
    data = dict(csrf=proof(page), expected=view["confirmation"], confirmed="yes")
    assert client.get(route).status_code == 405
    assert client.post(route, data={**data, "csrf": "wrong"},
                       headers={"Origin": ORIGIN}).status_code == 403
    assert client.post(route, data={**data, "confirmed": "no"},
                       headers={"Origin": ORIGIN}).status_code == 409
    assert client.post(route, data=data,
                       headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert client.post(route, data=data, headers={"Origin": ORIGIN},
                       follow_redirects=False).status_code == 303
    assert status(bundle, identifier, kind)["retry_count"] == 1


@pytest.mark.parametrize("kind", PREFIXES)
def test_deleted_and_stale_dreams_never_reactivate(client_env, kind):
    bundle = client_env
    identifier, _ = fail(bundle, kind)
    route = endpoint(identifier, kind) + "/retry"
    body = payload(status(bundle, identifier, kind))
    with bundle[0][2]() as db:
        apply_correction(db, db.get(Dream, bundle[0][5]), "Correction fictive P11 phase 4", 1)
        db.commit()
    assert bundle[1].post(route, json=body, headers=headers(bundle)).status_code == 409
    assert status(bundle, identifier, kind)["outdated"]
    with bundle[0][2]() as db:
        delete_dream(db, bundle[0][3], bundle[0][5])
    assert bundle[1].post(route, json=body, headers=headers(bundle)).status_code == 404


def test_safety_failure_is_not_retryable_and_no_private_metadata(client_env):
    bundle = client_env
    identifier = cases.queue(bundle[0], "image")
    assert cases.execute(bundle[0], "image", FakeEngine(error="safety_blocked"))
    view = status(bundle, identifier, "image")
    assert not view["retryable"] and "sécurité" in view["state_message"]
    response = bundle[1].post(endpoint(identifier, "image")+"/retry", json=payload(view),
                              headers=headers(bundle))
    assert response.status_code == 409
    for secret in ["claim_token", "lease_until", "storage_key", "input_snapshot", "model_path"]:
        assert secret not in str(view)


def test_explicit_regeneration_reuses_budget_and_requires_current_job(client_env):
    bundle = client_env
    identifier = cases.queue(bundle[0], "image")
    assert cases.execute(bundle[0], "image")
    for _ in range(2):
        view = status(bundle, identifier, "image")
        assert view["regeneratable"]
        body = payload(view)
        response = bundle[1].post(endpoint(identifier, "image")+"/regenerate", json=body,
                                  headers=headers(bundle))
        assert response.status_code == 202
        assert bundle[1].post(endpoint(identifier, "image")+"/regenerate", json=body,
                             headers=headers(bundle)).status_code == 409
        identifier = response.json()["job_id"]
        assert cases.execute(bundle[0], "image")
    view = status(bundle, identifier, "image")
    assert view["cycle_attempts"] == 3 and not view["regeneratable"]


def test_ajax_expired_session_returns_401_without_redirect_or_job(client_env):
    env, client, _ = client_env
    identifier = cases.queue(env, "stt")
    response = client.get(f"/reves/{env[5]}/transcription/{identifier}",
                          headers={"Accept": "application/json"}, follow_redirects=False)
    assert response.status_code == 401
    with env[2]() as db:
        assert db.get(Job, identifier).attempts == 0


def test_mismatched_description_is_outdated_even_when_input_lookup_refuses(client_env):
    bundle = client_env
    identifier, _ = fail(bundle, "image")
    with bundle[0][2]() as db:
        db.get(Dream, bundle[0][5]).text_version = 2
        db.get(Job, identifier).expected_text_version = 2
        db.get(ImageGeneration, identifier).text_version = 2
        assert db.get(ImageDescription, bundle[0][5]).text_version == 1
        db.commit()
    view = status(bundle, identifier, "image")
    assert view["outdated"] and not view["retryable"] and not view["regeneratable"]
    assert view["technical_state"] == "failed"


def test_stt_success_is_current_after_output_version_increment(client_env):
    bundle = client_env
    identifier = cases.queue(bundle[0], "stt")
    assert cases.execute(bundle[0], "stt")
    view = status(bundle, identifier, "stt")
    assert view["technical_state"] == "done" and not view["outdated"]
    assert "dépassé" not in view["state_message"]


@pytest.mark.parametrize("kind", ["stt", "emotion"])
def test_unknown_private_error_is_never_exposed(client_env, kind):
    bundle = client_env
    identifier, _ = fail(bundle, kind)
    with bundle[0][2]() as db:
        db.get(Job, identifier).error_code = "private/path/provider-detail"
        db.commit()
    response = bundle[1].get(endpoint(identifier, kind), headers=headers(bundle))
    assert response.status_code == 200 and response.json()["error_code"] == "unknown_error"
    assert "private/path" not in response.text and "provider-detail" not in response.text
    assert not response.json()["tracking"]["retryable"]


def test_web_regeneration_needs_csrf_confirmation_and_current_job(client_env):
    bundle = client_env
    env, client, tokens = bundle
    identifier = cases.queue(env, "image")
    assert cases.execute(env, "image")
    client.cookies.set(SESSION_COOKIE, tokens[0])
    page = client.get(f"/reves/{env[5]}/image")
    view = status(bundle, identifier, "image")
    route = f"/reves/{env[5]}/traitements/image/{identifier}/regenerer"
    data = dict(csrf=proof(page), expected=view["confirmation"], confirmed="yes")
    assert client.get(route).status_code == 405
    assert client.post(route, data={**data, "csrf": "wrong"},
                       headers={"Origin": ORIGIN}).status_code == 403
    assert client.post(route, data={**data, "confirmed": "no"},
                       headers={"Origin": ORIGIN}).status_code == 409
    assert client.post(route, data=data, headers={"Origin": ORIGIN},
                       follow_redirects=False).status_code == 303
    assert client.post(route, data=data, headers={"Origin": ORIGIN}).status_code == 409


def test_disabled_emotion_engine_refuses_retry_but_preserves_manual_choice(client_env, monkeypatch):
    bundle = client_env
    identifier, _ = fail(bundle, "emotion")
    monkeypatch.setenv("EMOTION_ENABLED", "0")
    view = status(bundle, identifier, "emotion")
    assert not view["retryable"]
    assert bundle[1].post(endpoint(identifier, "emotion")+"/retry", json=payload(view),
                          headers=headers(bundle)).status_code == 409
    with bundle[0][2]() as db:
        revision = db.get(DreamEmotion, bundle[0][5]).revision
    response = bundle[1].put(f"/api/v1/dreams/{bundle[0][5]}/emotion",
                             json=dict(emotion="triste", expected_revision=revision),
                             headers=headers(bundle))
    assert response.status_code == 200 and response.json()["value"] == "triste"


def test_stt_changed_story_allows_new_request_but_never_retry_of_old_input(client_env):
    env, client, tokens = client_env
    identifier, _ = fail(client_env, "stt")
    with env[2]() as db:
        apply_correction(db, db.get(Dream, env[5]), "Nouvelle correction fictive P11", 1)
        db.commit()
    client.cookies.set(SESSION_COOKIE, tokens[0])
    page = client.get(f"/reves/{env[5]}/transcription")
    import re
    button = re.search(r'<button id="stt-start"[^>]*>', page.text).group(0)
    assert "disabled=" not in button and not button.rstrip(">").endswith("disabled")
    assert not status(client_env, identifier, "stt")["retryable"]
    response = client.post(f"/api/v1/dreams/{env[5]}/transcriptions",
        json=dict(media_id=str(env[6]), expected_version=2), headers=headers(client_env))
    assert response.status_code == 202 and response.json()["id"] != str(identifier)


def test_image_incoherent_snapshot_is_hidden_before_any_browser_poll(client_env):
    env, client, tokens = client_env
    identifier = cases.queue(env, "image")
    assert cases.execute(env, "image")
    with env[2]() as db:
        db.get(ImageGeneration, identifier).description = "Incohérence fictive même version"
        db.commit()
    response = client.get(endpoint(identifier, "image"), headers=headers(client_env))
    assert response.json()["status"] == "outdated"
    assert response.json()["tracking"]["technical_state"] == "done"
    assert response.json()["tracking"]["outdated"] and response.json()["image_url"] is None
    client.cookies.set(SESSION_COOKIE, tokens[0])
    page = client.get(f"/reves/{env[5]}/image")
    import re
    figure = re.search(r'<figure id="image-result"[^>]*>', page.text).group(0)
    assert "hidden" in figure
