"""Pages P08 : PostgreSQL temporaire, HTTPS/CSRF et faux moteur uniquement."""

import re

import pytest
from fastapi.testclient import TestClient

from backend.app.emotion_provider import EmotionRequest
from backend.app.emotion_web import WARNING
from backend.app.models import Dream, EmotionAnalysis, Job
from backend.app.services import emotions
from backend.app.services.transcripts import apply_correction
from backend.app.web.security import SESSION_COOKIE
from backend.tests import test_emotion_postgresql as cases
from backend.tests.test_authentication import application_for
from backend.tests.test_emotion_contract import FakeEmotionProvider

pg_env = cases.env
pytestmark = pytest.mark.integration


@pytest.fixture
def web_env(pg_env, monkeypatch):
    monkeypatch.setenv("WEB_ORIGIN", "https://localhost:8443")
    monkeypatch.setenv("EMOTION_ENABLED", "0")
    with TestClient(application_for(pg_env[0]), base_url="https://localhost:8443") as client:
        client.cookies.set(SESSION_COOKIE, pg_env[4][0])
        yield pg_env, client


def base(env):
    return f"/reves/{env[0][3][2]}/emotion"


def fields(response):
    return {
        "csrf": re.search(r'name="csrf" value="([a-f0-9]+)"', response.text).group(1),
        "revision": re.search(r'name="revision" value="(\d+:\d+)"', response.text).group(1),
    }


def post(env, action, extra=None, raw=None):
    client = env[1]
    data = raw if raw is not None else {**fields(client.get(base(env))), **(extra or {})}
    return client.post(
        base(env) + "/" + action,
        data=data,
        headers={"Origin": "https://localhost:8443"},
        follow_redirects=False,
    )


def complete_fake(sessions, value="heureux", reason=None, reservation=None):
    identifier, token = reservation or emotions.claim(sessions)
    with sessions() as db:
        snapshot = db.get(EmotionAnalysis, identifier)
        request = EmotionRequest(
            request_id=identifier,
            text=snapshot.transcript,
            text_version=snapshot.text_version,
            choice_revision=snapshot.choice_revision,
        )
        result = (
            FakeEmotionProvider(value, reason)
            .analyze(request)
            .model_copy(
                update={
                    "engine": snapshot.parameters["engine"],
                    "model_revision": snapshot.parameters["model_revision"],
                }
            )
        )
    return emotions.finish(sessions, identifier, token, result)


def test_warning_disabled_manual_and_p09_filter(web_env):
    env, client = web_env
    page = client.get(base(web_env))
    assert page.status_code == 200 and WARNING in page.text
    assert "Récit actuel · version 1" in page.text
    assert 'id="emotion-request"' in page.text and "Moteur expérimental désactivé" in page.text
    assert post(web_env, "suggerer", {"text_version": "1"}).status_code == 409
    assert post(web_env, "choisir", {"emotion": "triste"}).status_code == 303
    page = client.get(base(web_env))
    assert "Choix manuel" in page.text
    assert "Triste" in client.get("/mes-reves?emotion=triste").text
    assert post(web_env, "retirer").status_code == 303
    assert "Choix retiré" in client.get(base(web_env)).text
    assert str(env[3][2]) in client.get("/mes-reves?emotion=non_renseignee").text
    assert f'href="{base(web_env)}"' in client.get(f"/reves/{env[3][2]}").text
    with env[2]() as db:
        assert db.query(Job).filter(Job.kind == "emotion").count() == 0


@pytest.mark.parametrize("action", ["choisir", "retirer", "accepter", "suggerer"])
def test_csrf_and_account_isolation(web_env, action, monkeypatch):
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    env, client = web_env
    extra = {
        "choisir": {"emotion": "heureux"},
        "retirer": {},
        "accepter": {"suggestion_id": str(env[3][2])},
        "suggerer": {"text_version": "1"},
    }[action]
    data = {**fields(client.get(base(web_env))), **extra}
    assert post(web_env, action, raw={**data, "csrf": "x" * 64}).status_code == 403
    assert client.post(base(web_env) + "/" + action, data=data).status_code == 403
    client.cookies.set(SESSION_COOKIE, env[4][1])
    home = client.get("/accueil")
    data = {
        "csrf": re.search(r'name="csrf" value="([a-f0-9]+)"', home.text).group(1),
        "revision": "1:0",
        **extra,
    }
    assert post(web_env, action, raw=data).status_code == 404
    assert client.get(base(web_env)).status_code == 404
    assert client.get(base(web_env) + "/statut").status_code == 404
    client.cookies.clear()
    assert client.get(base(web_env), follow_redirects=False).status_code == 303
    assert post(web_env, action, raw=data).status_code == 303


def test_suggestion_acceptance_versions_and_retained_value(web_env, monkeypatch):
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    env, client = web_env
    assert post(web_env, "suggerer", {"text_version": "1"}).status_code == 303
    assert client.get(base(web_env) + "/statut").json()["status"] == "queued"
    assert post(web_env, "suggerer", {"text_version": "1"}).status_code == 409
    assert complete_fake(env[2])
    view = client.get(base(web_env) + "/statut").json()
    assert view["status"] == "done" and view["value"] is None
    assert (
        post(web_env, "accepter", {"suggestion_id": view["suggestion"]["request_id"]}).status_code
        == 303
    )
    assert "Suggestion acceptée" in client.get(base(web_env)).text
    with env[2]() as db:
        dream = db.get(Dream, env[3][2], with_for_update=True)
        apply_correction(db, dream, "Un récit fictif entièrement corrigé.", 1)
        db.commit()
    view = client.get(base(web_env) + "/statut").json()
    assert view["suggestion"] is None and view["value"] == "heureux"
    assert view["status"] == "outdated"
    assert post(web_env, "accepter", {"suggestion_id": str(env[3][2])}).status_code == 409


def test_abstention_error_and_manual_choice_during_job(web_env, monkeypatch):
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    env, client = web_env
    post(web_env, "suggerer", {"text_version": "1"})
    assert complete_fake(env[2], None, "ambiguous")
    view = client.get(base(web_env) + "/statut").json()
    assert view["status"] == "abstention" and view["value"] is None
    assert (
        post(web_env, "accepter", {"suggestion_id": view["suggestion"]["request_id"]}).status_code
        == 409
    )
    post(web_env, "suggerer", {"text_version": "1"})
    assert emotions.claim(env[2]) is None  # L'abstention identique est réutilisée.
    with env[2]() as db:
        dream = db.get(Dream, env[3][2], with_for_update=True)
        apply_correction(db, dream, "Nouveau récit fictif pour tester un conflit.", 1)
        db.commit()
    post(web_env, "suggerer", {"text_version": "2"})
    identifier, token = emotions.claim(env[2])
    assert client.get(base(web_env) + "/statut").json()["status"] == "running"
    stale_form = fields(client.get(base(web_env)))
    assert post(web_env, "choisir", {"emotion": "autre"}).status_code == 303
    assert post(web_env, "retirer", raw=stale_form).status_code == 409
    assert not emotions.finish(env[2], identifier, token, error="timeout")
    assert client.get(base(web_env) + "/statut").json()["value"] == "autre"
    post(web_env, "suggerer", {"text_version": "2"})
    identifier, token = emotions.claim(env[2])
    emotions.finish(env[2], identifier, token, error="model_unavailable")
    assert client.get(base(web_env) + "/statut").json()["status"] == "failed"


def test_invalid_forms_and_html_escape(web_env):
    env, client = web_env
    with env[2]() as db:
        db.get(Dream, env[3][2]).transcript = "<script>alert('fiction')</script>"
        db.commit()
    page = client.get(base(web_env))
    assert "&lt;script&gt;" in page.text and "<script>alert" not in page.text
    assert post(web_env, "choisir", {"emotion": "non_renseignee"}).status_code == 422
    data = fields(client.get(base(web_env)))
    assert post(web_env, "retirer", raw={**data, "revision": "-1"}).status_code == 422
    assert post(web_env, "retirer", raw={**data, "user_id": str(env[3][1])}).status_code == 400


def test_text_change_before_first_choice_rejects_old_form(web_env):
    env, client = web_env
    old = fields(client.get(base(web_env)))
    with env[2]() as db:
        dream = db.get(Dream, env[3][2], with_for_update=True)
        apply_correction(db, dream, "Une fiction corrigée avant le premier choix.", 1)
        db.commit()
    assert post(web_env, "choisir", raw={**old, "emotion": "heureux"}).status_code == 409
    with env[2]() as db:
        assert db.get(Dream, env[3][2]).emotion is None


@pytest.mark.parametrize("old_emotion", [None, "heureux"])
def test_incomplete_and_historical_dream_remain_editable(web_env, old_emotion):
    env, client = web_env
    with env[2]() as db:
        dream = db.get(Dream, env[3][2])
        dream.transcript, dream.text_version, dream.emotion = None, 0, old_emotion
        db.commit()
    response = client.get(base(web_env))
    assert "Aucun récit enregistré" in response.text
    if old_emotion:
        assert "Valeur historique de provenance inconnue" in response.text
    assert post(web_env, "choisir", {"emotion": "neutre"}).status_code == 303
