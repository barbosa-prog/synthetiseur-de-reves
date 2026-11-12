"""Historique P09 sur PostgreSQL temporaire, données entièrement fictives."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.app.history_schemas import HistoryQuery
from backend.app.models import AuthSession, Dream, User
from backend.app.security import new_token, token_digest
from backend.app.services.history import list_dreams
from backend.app.web.security import SESSION_COOKIE
from backend.tests.test_authentication import application_for

pytestmark = pytest.mark.integration
EMOTIONS = [None, "heureux", "stressant", "neutre", "triste", "autre"]


@pytest.fixture
def environment(database):
    engine, _ = database
    now = datetime.now(timezone.utc)
    tokens = [new_token(), new_token()]
    with Session(engine) as db:
        users = [User(email="history-owner@example.com"), User(email="history-other@example.com")]
        db.add_all(users)
        db.flush()
        ids = [user.id for user in users]
        for user, token in zip(users, tokens):
            db.add(AuthSession(user_id=user.id, token_hash=token_digest(token),
                               expires_at=now+timedelta(hours=1)))
        for number in range(1, 26):
            db.add(Dream(id=uuid.UUID(int=number), user_id=ids[0], created_at=now,
                         emotion=EMOTIONS[(number-1) % 6],
                         transcript="Fiction "*100 if number == 25 else None,
                         text_version=1 if number == 25 else 0))
        db.add(Dream(user_id=ids[0], status="deleted", deleted_at=now,
                     created_at=now+timedelta(days=1), transcript="Deleted fictional text"))
        db.add(Dream(user_id=ids[1], created_at=now+timedelta(days=2),
                     emotion="neutre", transcript="Other account fictional text"))
        db.commit()
    with TestClient(application_for(engine)) as client:
        yield engine, client, ids, tokens


def headers(env, account=0):
    return {"Authorization": "Bearer "+env[3][account]}


def test_owner_incomplete_deleted_and_stable_tie_order(environment):
    engine, client, ids, _ = environment
    response = client.get("/api/v1/dreams", headers=headers(environment))
    assert response.status_code == 200
    data = response.json()
    assert (data["page"], data["page_size"], data["total"], data["total_pages"]) == (1, 12, 25, 3)
    assert data["has_next"] and not data["has_previous"]
    assert [uuid.UUID(item["id"]).int for item in data["items"]] == list(range(25, 13, -1))
    assert data["items"][0]["has_transcript"] and len(data["items"][0]["excerpt"]) == 200
    assert not data["items"][1]["has_transcript"] and data["items"][1]["excerpt"] is None
    assert all(item["status"] == "draft" for item in data["items"])
    forbidden = {"user_id", "storage_key", "media_id", "transcript", "parameters"}
    assert not forbidden & set(data["items"][0])
    other = client.get("/api/v1/dreams", headers=headers(environment, 1)).json()
    assert other["total"] == 1 and other["items"][0]["excerpt"] == "Other account fictional text"
    with Session(engine) as db:
        assert list_dreams(db, uuid.uuid4(), HistoryQuery()).total == 0
        assert db.scalar(select(Dream).where(Dream.user_id == ids[1])).emotion == "neutre"


def test_pagination_reconnect_and_distinct_creation_dates(environment):
    engine, client, ids, _ = environment
    with Session(engine) as db:
        old = db.get(Dream, uuid.UUID(int=1))
        old.created_at += timedelta(days=1)
        db.commit()
    engine.dispose()
    pages = [client.get("/api/v1/dreams", headers=headers(environment),
                        params={"page": page}).json() for page in (1, 2, 3, 4)]
    identifiers = [item["id"] for page in pages[:3] for item in page["items"]]
    assert len(identifiers) == len(set(identifiers)) == 25
    assert uuid.UUID(identifiers[0]).int == 1
    assert len(pages[2]["items"]) == 1 and not pages[2]["has_next"]
    assert pages[3]["items"] == [] and pages[3]["total"] == 25
    assert pages[1]["has_previous"]
    for size in (1, 50):
        result = client.get("/api/v1/dreams", headers=headers(environment),
                            params={"page_size": size}).json()
        assert len(result["items"]) == min(size, 25)


@pytest.mark.parametrize("emotion", EMOTIONS)
def test_each_emotion_and_null_is_not_neutral(environment, emotion):
    engine, client, ids, _ = environment
    value = emotion or "non_renseignee"
    result = client.get("/api/v1/dreams", headers=headers(environment),
                        params={"emotion": value, "page_size": 50}).json()
    assert result["emotion"] == value
    assert result["total"] == (5 if emotion is None else 4)
    assert all(item["emotion"] == emotion for item in result["items"])
    # Lecture seule : aucune émotion ni aucun récit modifié par la consultation.
    with Session(engine) as db:
        dreams = db.scalars(select(Dream).where(Dream.user_id == ids[0], Dream.status != "deleted")
                            .order_by(Dream.id)).all()
        assert [dream.emotion for dream in dreams] == [EMOTIONS[n % 6] for n in range(25)]


def test_empty_filtered_page_and_no_media_join(environment):
    engine, client, _, _ = environment
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = client.get("/api/v1/dreams", headers=headers(environment),
                            params={"emotion": "heureux", "page": 2}).json()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["total"] == 4 and result["items"] == []
    empty = client.get("/api/v1/dreams", headers=headers(environment, 1),
                       params={"emotion": "heureux"}).json()
    assert empty["total"] == empty["total_pages"] == 0 and empty["items"] == []
    assert not empty["has_previous"] and not empty["has_next"]
    history = [s for s in statements if "history_total" in s]
    assert len(history) == 1
    assert "FOR UPDATE" not in history[0] and "media" not in history[0]


def test_authentication_expiration_and_cookie_cannot_replace_bearer(environment):
    engine, client, _, tokens = environment
    assert client.get("/api/v1/dreams").status_code == 401
    client.cookies.set(SESSION_COOKIE, tokens[0])
    assert client.get("/api/v1/dreams").status_code == 401
    for token in ("invalid", new_token()):
        response = client.get("/api/v1/dreams", headers={"Authorization": "Bearer "+token})
        assert response.status_code == 401
    with Session(engine) as db:
        session = db.scalar(select(AuthSession).where(
            AuthSession.token_hash == token_digest(tokens[0])))
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    assert client.get("/api/v1/dreams", headers=headers(environment)).status_code == 401
