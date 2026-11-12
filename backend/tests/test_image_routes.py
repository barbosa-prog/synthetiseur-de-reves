"""Routes P07 avec PostgreSQL et faux moteur, sans GPU."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app.database import session_factory
from backend.app.models import Dream
from backend.app.services.image_execution import run_once
from backend.app.services.image_jobs import claim
from backend.app.web.security import SESSION_COOKIE
from backend.tests.test_authentication import application_for
from backend.tests.test_image_execution import FakeEngine
from backend.tests.test_media import media_environment as media_setup  # noqa: F401
from backend.tests.test_web import proof

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:8443"


@pytest.fixture
def environment(request):
    env = request.getfixturevalue("media_setup")
    client, engine, _, _, _, _, dream, owner, *_ = env
    with session_factory(engine)() as db:
        row = db.get(Dream, dream)
        row.transcript, row.text_version = "Récit français fictif.", 1
        db.commit()
    return env


def save(env, description="An enchanted forest", expected=0, text_version=1):
    return env[0].put(f"/api/v1/dreams/{env[6]}/image-description", headers=env[7], json={
        "description": description, "text_version": text_version, "expected_version": expected})


def start(env):
    return env[0].post(f"/api/v1/dreams/{env[6]}/images", headers=env[7], json={
        "text_version": 1, "description_version": 1})


def test_full_web_api_and_private_result(environment):
    env = environment
    client, engine, storage, _, _, _, dream, owner, other, _ = env
    assert save(env).status_code == 200
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    assert "Créer une image du rêve" in client.get(f"/reves/{dream}/recit").text
    page = client.get(f"/reves/{dream}/image")
    assert 'maxlength="500"' in page.text and "Aucune traduction" in page.text
    csrf = proof(page)
    response = client.post(f"/reves/{dream}/image/generer", headers={"Origin": ORIGIN},
                           data={"csrf": csrf, "expected_version": "1:1"}, follow_redirects=False)
    assert response.status_code == 303
    status = client.get(f"/reves/{dream}/image/statut").json()
    assert status["status"] == "queued" and status["busy"]
    assert start(env).status_code == 409
    run_once(session_factory(engine), storage, FakeEngine())
    status = client.get(f"/reves/{dream}/image/statut").json()
    assert status["status"] == "done" and not status["busy"]
    assert client.get(status["image_url"]).status_code == 200
    api = client.get(f"/api/v1/images/{status['job_id']}", headers=owner).json()
    assert api["image_url"].startswith("/api/v1/media/")
    assert client.get(api["image_url"], headers=other).status_code == 404
    assert "storage_key" not in str(status) and "claim_token" not in str(status)


@pytest.mark.parametrize("description", ["", "   ", "x"*501, "bad\x00value"])
def test_description_validation(environment, description):
    assert save(environment, description).status_code == 422


def test_permissions_csrf_and_xss(environment):
    env = environment
    client, _, _, _, _, _, dream, owner, other, _ = env
    assert client.get(f"/api/v1/dreams/{dream}/image-description").status_code == 401
    assert client.get(f"/api/v1/dreams/{dream}/image-description", headers=other).status_code == 404
    assert client.get(f"/api/v1/dreams/{uuid.uuid4()}/image-description",
                      headers=owner).status_code == 404
    assert save(env, "<script>alert('fiction')</script>").status_code == 200
    identifier = start(env).json()["job_id"]
    assert client.get(f"/api/v1/images/{identifier}", headers=other).status_code == 404
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    page = client.get(f"/reves/{dream}/image")
    assert "&lt;script&gt;" in page.text and "<script>alert" not in page.text
    for suffix, fields in (("description", {"description": "test", "expected_version": "1:1"}),
                           ("generer", {"expected_version": "1:1"})):
        assert client.post(f"/reves/{dream}/image/{suffix}", headers={"Origin": ORIGIN},
                           data={**fields, "csrf": "invalid"}).status_code == 403
    client.cookies.set(SESSION_COOKIE, other["Authorization"].split()[1])
    assert client.get(f"/reves/{dream}/image").status_code == 404


@pytest.mark.parametrize("change", ["text", "description"])
def test_changes_during_generation_web_outdated(environment, change):
    env = environment
    assert save(env).status_code == 200
    identifier = start(env).json()["job_id"]

    def callback():
        if change == "text":
            assert env[0].patch(f"/api/v1/dreams/{env[6]}/transcript", headers=env[7], json={
                "transcript": "Récit fictif modifié.", "expected_version": 1}).status_code == 200
        else:
            assert save(env, "New fictional moon", expected=1).status_code == 200

    run_once(session_factory(env[1]), env[2], FakeEngine(callback))
    state = env[0].get(f"/api/v1/images/{identifier}", headers=env[7]).json()
    assert state["status"] == "outdated" and state["image_url"] is None


@pytest.mark.parametrize("code,word", [("safety_blocked", "filtre"), ("timeout", "délai"),
                                      ("insufficient_memory", "Mémoire")])
def test_error_messages(environment, code, word):
    assert save(environment).status_code == 200
    identifier = start(environment).json()["job_id"]
    run_once(session_factory(environment[1]), environment[2], FakeEngine(error=code))
    state = environment[0].get(f"/api/v1/images/{identifier}", headers=environment[7]).json()
    assert state["status"] == "failed" and word in state["message"]
    assert state["image_url"] is None


def test_concurrent_http_requests(environment):
    env = environment
    assert save(env).status_code == 200

    def submit(_):
        with TestClient(application_for(env[1])) as client:
            return client.post(f"/api/v1/dreams/{env[6]}/images", headers=env[7], json={
                "text_version": 1, "description_version": 1}).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(submit, range(2))) == [202, 409]


def test_running_status_and_anonymous_pages(environment):
    env = environment
    assert save(env).status_code == 200
    identifier = start(env).json()["job_id"]
    assert claim(session_factory(env[1])) is not None
    state = env[0].get(f"/api/v1/images/{identifier}", headers=env[7]).json()
    assert state["status"] == "running" and state["busy"]
    assert env[0].get(f"/reves/{env[6]}/image", follow_redirects=False).status_code == 303
    assert env[0].get(f"/api/v1/images/{uuid.uuid4()}", headers=env[7]).status_code == 404


def test_web_description_errors_preserve_input_and_enforce_csrf(environment):
    env = environment
    client, _, _, _, _, _, dream, owner, *_ = env
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    url = f"/reves/{dream}/image"
    csrf = proof(client.get(url))
    fields = {"csrf": csrf, "description": "A fictional forest", "expected_version": "1:0"}
    assert client.post(url+"/description", headers={"Origin": "https://elsewhere.example"},
                       data=fields).status_code == 403
    assert client.post(url+"/description", headers={"Origin": ORIGIN}, data=fields,
                       follow_redirects=False).status_code == 303
    stale = client.post(url+"/description", headers={"Origin": ORIGIN},
                        data={**fields, "description": "My unsaved correction"})
    assert stale.status_code == 409 and "My unsaved correction" in stale.text
    invalid = client.post(url+"/description", headers={"Origin": ORIGIN},
                          data={**fields, "description": " ", "expected_version": "1:1"})
    assert invalid.status_code == 422 and "1 à 500" in invalid.text
    assert client.post(url+"/generer", headers={"Origin": ORIGIN},
                       data={"csrf": csrf, "expected_version": "invalid"}).status_code == 422
    start(env)
    assert client.post(url+"/generer", headers={"Origin": ORIGIN},
                       data={"csrf": csrf, "expected_version": "1:1"}).status_code == 409


def test_api_description_optimistic_conflict(environment):
    assert save(environment).status_code == 200
    conflict = save(environment, "Other fictitious text")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "image_version_conflict"
