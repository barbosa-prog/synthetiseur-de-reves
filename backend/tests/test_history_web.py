"""P09 HTML : PostgreSQL temporaire, cookies et médias synthétiques uniquement."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.database import session_factory
from backend.app.models import Dream
from backend.app.services import image_jobs
from backend.app.services.image_execution import run_once
from backend.app.services.transcripts import apply_correction
from backend.app.storage.local import LocalPrivateStorage
from backend.app.web.security import SESSION_COOKIE
from backend.tests.test_authentication import application_for
from backend.tests.test_history import EMOTIONS
from backend.tests.test_history import environment as history_environment  # noqa: F401
from backend.tests.test_image_execution import FakeEngine

pytestmark = pytest.mark.integration


@pytest.fixture
def environment(request, monkeypatch):
    env = request.getfixturevalue("history_environment")
    monkeypatch.setenv("WEB_ORIGIN", "https://localhost:8443")
    with TestClient(application_for(env[0]), base_url="https://localhost:8443") as client:
        client.cookies.set(SESSION_COOKIE, env[3][0])
        yield env[0], client, *env[2:]


def item_ids(response):
    values = re.findall(r'data-dream-id="([a-f0-9-]+)"', response.text)
    return [uuid.UUID(value).int for value in values]


def test_list_default_pages_tie_order_and_incomplete(environment):
    _, client, _, _ = environment
    response = client.get("/mes-reves")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert item_ids(response) == list(range(25, 13, -1))
    assert "Aucun récit enregistré" in response.text
    assert "Other account fictional text" not in response.text
    assert "Deleted fictional text" not in response.text
    assert "Page 1 sur 3" in response.text
    assert "Page précédente" not in response.text
    assert item_ids(client.get("/mes-reves?page=2")) == list(range(13, 1, -1))
    third = client.get("/mes-reves?page=3")
    assert item_ids(third) == [1] and "Page suivante" not in third.text
    beyond = client.get("/mes-reves?page=4")
    assert "Aucun rêve sur cette page" in beyond.text and not item_ids(beyond)


@pytest.mark.parametrize("emotion", EMOTIONS)
def test_each_filter_and_reset(environment, emotion):
    engine, client, ids, _ = environment
    value = emotion or "non_renseignee"
    response = client.get("/mes-reves", params={"emotion": value})
    assert response.status_code == 200
    expected = [number for number in range(25, 0, -1) if EMOTIONS[(number-1) % 6] == emotion]
    assert item_ids(response) == expected
    assert f'value="{value}" selected' in response.text
    assert len(item_ids(client.get("/mes-reves?emotion="))) == 12
    with Session(engine) as db:
        assert db.get(Dream, uuid.UUID(int=1)).emotion is None


def test_filter_preserved_in_pagination(environment):
    engine, client, ids, _ = environment
    with Session(engine) as db:
        for _ in range(13):
            db.add(Dream(user_id=ids[0], emotion="heureux"))
        db.commit()
    page = client.get("/mes-reves?emotion=heureux")
    assert 'href="/mes-reves?page=2&amp;emotion=heureux"' in page.text
    second = client.get("/mes-reves?page=2&emotion=heureux")
    assert 'href="/mes-reves?page=1&amp;emotion=heureux"' in second.text
    assert 'value="heureux" selected' in second.text


@pytest.mark.parametrize("query", ["page=0", "page=10001", "page_size=1", "page_size=13",
                                   "emotion=unknown", "user_id=other", "page=1.2"])
def test_invalid_web_parameters(environment, query):
    assert environment[1].get("/mes-reves?"+query).status_code == 422


def test_private_detail_empty_history_and_xss(environment):
    engine, client, ids, tokens = environment
    own = uuid.UUID(int=1)
    with Session(engine) as db:
        dream = db.get(Dream, own)
        dream.transcript, dream.text_version = "<script>alert('fiction')</script>", 1
        db.commit()
    detail = client.get(f"/reves/{own}")
    assert detail.status_code == 200 and "&lt;script&gt;" in detail.text
    assert "<script>alert" not in detail.text
    assert f'href="/reves/{own}/recit"' in detail.text
    assert f'href="/reves/{own}/image"' in detail.text
    assert "Aucun audio disponible" in detail.text
    assert "&lt;script&gt;" in client.get("/mes-reves?page=3").text
    client.cookies.set(SESSION_COOKIE, tokens[1])
    assert client.get(f"/reves/{own}").status_code == 404
    assert client.get(f"/reves/{uuid.uuid4()}").status_code == 404
    empty = client.get("/mes-reves?emotion=heureux")
    assert "Aucun rêve à afficher" in empty.text
    client.cookies.clear()
    for path in ("/mes-reves", f"/reves/{own}"):
        assert client.get(path, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("change", ["text", "description"])
def test_current_image_and_version_invalidation(environment, tmp_path, change):
    engine, client, ids, tokens = environment
    dream_id = uuid.UUID(int=25)
    sessions = session_factory(engine)
    storage = LocalPrivateStorage(tmp_path/"private-image-test")
    with sessions() as db:
        image_jobs.save_description(db, ids[0], dream_id, "A fictional forest", 1, 0)
        image_jobs.enqueue(db, ids[0], dream_id, 1, 1)
    assert run_once(sessions, storage, FakeEngine())
    detail = client.get(f"/reves/{dream_id}")
    image_url = re.search(r'src="(/web/media/[^\"]+)"', detail.text).group(1)
    client.app.state.media_storage = storage
    assert client.get(image_url).status_code == 200
    if change == "description":
        with sessions() as db:
            image_jobs.save_description(db, ids[0], dream_id, "New fictional forest", 1, 1)
    else:
        with sessions() as db:
            dream = db.get(Dream, dream_id, with_for_update=True)
            apply_correction(db, dream, "New fictional text", 1)
            db.commit()
    stale = client.get(f"/reves/{dream_id}")
    assert image_url not in stale.text and 'id="current-image-panel"' in stale.text
    client.cookies.set(SESSION_COOKIE, tokens[1])
    assert client.get(image_url).status_code == 404


def test_deleted_and_incomplete_detail(environment):
    engine, client, ids, _ = environment
    with Session(engine) as db:
        deleted = db.query(Dream).filter(Dream.user_id == ids[0], Dream.status == "deleted").one()
        deleted_id = deleted.id
    assert client.get(f"/reves/{deleted_id}").status_code == 404
    detail = client.get(f"/reves/{uuid.UUID(int=1)}")
    assert "Aucun récit enregistré" in detail.text
    assert "Aucune image actuelle" in detail.text
    assert "Écrire le récit" in detail.text
