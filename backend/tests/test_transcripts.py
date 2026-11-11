"""Éditeur et contrôle de version P06 sur PostgreSQL réel."""

import io
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import Dream, Media
from backend.app.web.security import SESSION_COOKIE
from backend.tests.audio_fixtures import audio_sample
from backend.tests.test_authentication import application_for
from backend.tests.test_media import media_environment as media_setup  # noqa: F401
from backend.tests.test_web import proof

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:8443"


@pytest.fixture(name="environment")
def shared_environment(request):
    return request.getfixturevalue("media_setup")


def api_path(dream):
    return f"/api/v1/dreams/{dream}/transcript"


def test_save_modify_version_and_reload(environment, caplog):
    client, engine, _, _, _, _, dream, owner, *_ = environment
    path = api_path(dream)
    initial = client.get(path, headers=owner)
    assert initial.status_code == 200 and initial.json()["text_version"] == 0
    response = client.patch(path, headers=owner, json={
        "transcript": "  Récit fictif de lune.  ", "expected_version": 0,
    })
    assert response.status_code == 200 and response.json()["text_version"] == 1
    assert response.json()["transcript"] == "Récit fictif de lune."
    assert response.json()["text_updated_at"] is not None
    assert client.patch(path, headers=owner, json={
        "transcript": "Récit fictif de lune.", "expected_version": 1,
    }).json()["text_version"] == 1
    assert client.patch(path, headers=owner, json={
        "transcript": "Correction fictive.", "expected_version": 1,
    }).json()["text_version"] == 2
    engine.dispose()
    assert client.get(path, headers=owner).json()["transcript"] == "Correction fictive."
    assert "Correction fictive." not in caplog.text


@pytest.mark.parametrize("text", ["", " \t\n", "a" * 20001, "a\x00b"])
def test_invalid_text_does_not_mutate(environment, text):
    client, engine, _, _, _, _, dream, owner, *_ = environment
    response = client.patch(api_path(dream), headers=owner, json={
        "transcript": text, "expected_version": 0,
    })
    assert response.status_code == 422
    with Session(engine) as db:
        row = db.get(Dream, dream)
        assert row.transcript is None and row.text_version == 0


def test_limit_and_protection_for_both_accounts(environment):
    client, _, _, _, _, _, dream, owner, other, _ = environment
    path = api_path(dream)
    assert client.get(path).status_code == 401
    assert client.patch(path, json={
        "transcript": "Fictif", "expected_version": 0,
    }).status_code == 401
    assert client.get(path, headers=other).status_code == 404
    assert client.patch(path, headers=other, json={
        "transcript": "Intrusion fictive", "expected_version": 0,
    }).status_code == 404
    assert client.get(api_path(uuid.uuid4()), headers=owner).status_code == 404
    assert client.get(api_path("not-a-uuid"), headers=owner).status_code == 422
    assert client.patch(path, headers=owner, json={
        "transcript": "🌙" * 20000, "expected_version": 0,
    }).status_code == 200


def test_stale_version_and_legacy_api_are_consistent(environment):
    client, _, _, _, _, _, dream, owner, *_ = environment
    legacy = f"/api/v1/dreams/{dream}"
    assert client.patch(legacy, headers=owner, json={
        "transcript": "Premier récit fictif",
    }).status_code == 200
    assert client.get(api_path(dream), headers=owner).json()["text_version"] == 1
    assert client.patch(api_path(dream), headers=owner, json={
        "transcript": "Ancien onglet fictif", "expected_version": 0,
    }).status_code == 409
    assert client.patch(legacy, headers=owner, json={
        "transcript": "Autre onglet fictif", "expected_text_version": 0,
    }).status_code == 409
    assert client.get(api_path(dream), headers=owner).json()["transcript"] == "Premier récit fictif"


def test_concurrent_corrections_only_one_wins(environment):
    _, engine, _, _, _, _, dream, owner, *_ = environment
    # Applications préparées avant les threads pour éviter la génération concurrente de schémas.
    applications = [application_for(engine) for _ in range(2)]

    def save(index):
        with TestClient(applications[index]) as client:
            return client.patch(api_path(dream), headers=owner, json={
                "transcript": f"Correction fictive {index}", "expected_version": 0,
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2))) == [200, 409]
    with Session(engine) as db:
        assert db.get(Dream, dream).text_version == 1


def web_submit(client, path, text, version=0, *, token=None, origin=ORIGIN):
    page = client.get(path)
    if page.status_code != 200:
        page = client.get("/connexion")
    return client.post(path, data={
        "transcript": text, "expected_version": str(version),
        "csrf": proof(page) if token is None else token,
    }, headers={"Origin": origin}, follow_redirects=False)


def test_web_editor_preserves_audio_and_text(environment):
    client, engine, _, service, alice, _, dream, owner, other, _ = environment
    identifier = service.store(alice, dream, io.BytesIO(audio_sample()),
                               kind="audio", media_format="wav")
    media_path = f"/api/v1/media/{identifier}/content"
    audio_before = client.get(media_path, headers=owner).content
    path = f"/reves/{dream}/recit"
    assert client.get(path, follow_redirects=False).status_code == 303
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    assert client.get(path).status_code == 200
    response = web_submit(client, path, "Récit fictif manuel.")
    assert response.status_code == 303
    saved = client.get(response.headers["location"])
    assert "Votre récit a été enregistré" in saved.text
    assert "Récit fictif manuel." in client.get(path).text
    assert client.get(media_path, headers=owner).content == audio_before
    with Session(engine) as db:
        assert db.get(Media, identifier).storage_state == "ready"
    client.cookies.set(SESSION_COOKIE, other["Authorization"].split()[1])
    assert client.get(path).status_code == 404
    assert web_submit(client, path, "Intrusion fictive").status_code == 404


def test_web_validation_csrf_xss_and_conflict(environment):
    client, engine, _, _, _, _, dream, owner, *_ = environment
    client.cookies.set(SESSION_COOKIE, owner["Authorization"].split()[1])
    path = f"/reves/{dream}/recit"
    assert web_submit(client, path, " ").status_code == 422
    assert web_submit(client, path, "a" * 20001).status_code == 422
    assert web_submit(client, path, "Récit fictif", token="invalid").status_code == 403
    assert web_submit(client, path, "Récit fictif",
                       origin="https://evil.example").status_code == 403
    malicious = '</textarea><script>window.fictitiousXSS=true</script>'
    assert web_submit(client, path, malicious).status_code == 303
    page = client.get(path)
    assert malicious not in page.text and "&lt;/textarea&gt;&lt;script&gt;" in page.text
    assert web_submit(client, path, "Autre saisie fictive", version=0).status_code == 409
    conflict = web_submit(client, path, "Mon texte fictif non perdu", version=0)
    assert "Mon texte fictif non perdu" in conflict.text
    assert re.search(r'name="expected_version" value="0"', conflict.text)
    with Session(engine) as db:
        assert db.get(Dream, dream).transcript == malicious


def test_migration_preserves_existing_text(environment):
    _, engine, _, _, _, _, dream, *_, config = environment
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "0004")
        from sqlalchemy import text

        db.execute(text("UPDATE dreams SET transcript = :text WHERE id = :id"),
                   {"text": "Ancien récit fictif conservé", "id": dream})
        command.upgrade(config, "head")
    with Session(engine) as db:
        row = db.get(Dream, dream)
        assert row.transcript == "Ancien récit fictif conservé" and row.text_version == 1
        assert row.text_updated_at is None
