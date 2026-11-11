"""Recette P03 sur PostgreSQL réel et comptes fictifs sans envoi d'e-mail."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.auth import get_db
from backend.app.main import create_app
from backend.app.models import AuthSession, AuthThrottle, Dream, Job, Media, User
from backend.app.security import token_digest

pytestmark = pytest.mark.integration
PASSWORD = "fictional passphrase P03 only"


def application_for(engine):
    application = create_app()

    def test_db():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    application.dependency_overrides[get_db] = test_db
    return application


@pytest.fixture
def auth_client(database):
    engine, _ = database
    with TestClient(application_for(engine)) as client:
        yield client, engine


def signup(client, email="alice@example.com"):
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    assert set(response.json()) == {"id", "email"}
    return response.json()["id"]


def signin(client, email="alice@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def authorization(client, email="alice@example.com"):
    response = signin(client, email)
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_registration_duplicate_and_hashed_storage(auth_client, caplog):
    client, engine = auth_client
    identifier = signup(client)
    response = client.post("/api/v1/auth/register", json={
        "email": "ALICE@example.com", "password": PASSWORD,
    })
    assert response.status_code == 409
    with Session(engine) as db:
        user = db.get(User, uuid.UUID(identifier))
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != PASSWORD
    assert PASSWORD not in caplog.text
    assert PASSWORD not in response.text


def test_login_session_storage_restart_and_logout(auth_client, caplog):
    client, engine = auth_client
    signup(client)
    response = signin(client)
    token = response.json()["access_token"]
    assert response.status_code == 200 and len(token) == 43
    assert response.headers["cache-control"] == "no-store"
    with Session(engine) as db:
        row = db.scalar(select(AuthSession))
        assert row.token_hash == token_digest(token) and row.token_hash != token
        assert row.expires_at - row.created_at == timedelta(hours=8)
    headers = {"Authorization": "Bearer " + token}
    # Nouvelle application / nouvelles connexions : aucune session en mémoire serveur.
    engine.dispose()
    with TestClient(application_for(engine)) as other_client:
        response = other_client.get("/api/v1/auth/session", headers=headers)
        assert response.status_code == 200
        assert token not in response.text and "password_hash" not in response.text
        assert other_client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/session", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 401
    assert token not in caplog.text and PASSWORD not in caplog.text


def test_wrong_password_absent_and_legacy_account(auth_client):
    client, engine = auth_client
    signup(client)
    with Session(engine) as db:
        db.add(User(email="legacy@example.com"))
        db.commit()
    responses = [signin(client, password="incorrect fictional password"),
                 signin(client, "absent@example.com"), signin(client, "legacy@example.com")]
    assert all(r.status_code == 401 for r in responses)
    assert len({r.text for r in responses}) == 1


def test_expiration_tampering_and_session_independence(auth_client):
    client, engine = auth_client
    signup(client)
    first, second = authorization(client), authorization(client)
    token = first["Authorization"].split()[1]
    with Session(engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=9)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/session", headers=first).status_code == 401
    assert client.get("/api/v1/auth/session", headers=second).status_code == 200
    fake = {"Authorization": "Bearer " + ("A" if token[0] != "A" else "B") + token[1:]}
    assert client.get("/api/v1/auth/session", headers=fake).status_code == 401


def seed_dream(engine, user_id):
    with Session(engine) as db:
        dream = Dream(user_id=uuid.UUID(user_id), transcript="Récit fictif P03.")
        db.add(dream)
        db.flush()
        db.add(Media(dream_id=dream.id, kind="image", storage_key="fictitious/private/image"))
        db.add(Job(dream_id=dream.id, kind="image"))
        db.commit()
        return str(dream.id)


def test_owner_and_cross_account_crud(auth_client):
    client, engine = auth_client
    alice = signup(client)
    signup(client, "bob@example.com")
    owner, stranger = authorization(client), authorization(client, "bob@example.com")
    identifier = seed_dream(engine, alice)
    path = "/api/v1/dreams/" + identifier
    assert client.get(path, headers=owner).status_code == 200
    absent = client.get("/api/v1/dreams/" + str(uuid.uuid4()), headers=stranger)
    for method in ["GET", "PATCH", "DELETE"]:
        response = client.request(method, path, headers=stranger,
                                  **({"json": {"transcript": "Intrusion fictive"}}
                                     if method == "PATCH" else {}))
        assert response.status_code == 404 and response.json() == absent.json()
    assert client.get(path, headers=owner).json()["transcript"] == "Récit fictif P03."
    response = client.patch(path, headers=owner, json={
        "transcript": "Correction fictive", "expected_text_version": 0,
    })
    assert response.status_code == 200 and response.json()["transcript"] == "Correction fictive"
    assert client.patch(path, headers=owner, json={"user_id": alice}).status_code == 422
    assert client.delete(path, headers=owner).status_code == 204
    assert client.get(path, headers=owner).status_code == 404
    with Session(engine) as db:
        assert db.get(Dream, uuid.UUID(identifier)).status == "deleted"
        # Les références restent intactes : aucune purge physique P19 anticipée.
        assert db.scalar(select(Media)) is not None and db.scalar(select(Job)) is not None


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_uuid_changes_and_invalid_uuid(auth_client, method):
    client, _ = auth_client
    signup(client)
    headers = authorization(client)
    kwargs = {"json": {"emotion": "neutre"}} if method == "PATCH" else {}
    assert client.request(method, "/api/v1/dreams/" + str(uuid.uuid4()),
                          headers=headers, **kwargs).status_code == 404
    assert client.request(method, "/api/v1/dreams/not-a-uuid",
                          headers=headers, **kwargs).status_code == 422


def test_persistent_throttle_and_window_reset(auth_client):
    client, engine = auth_client
    for _ in range(5):
        assert signin(client, "absent@example.com").status_code == 401
    with TestClient(application_for(engine)) as second:
        response = signin(second, "absent@example.com")
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    with Session(engine) as db:
        for bucket in db.scalars(select(AuthThrottle)):
            bucket.window_start -= timedelta(minutes=16)
        db.commit()
    assert signin(client, "absent@example.com").status_code == 401


def test_parallel_throttle(auth_client):
    client, engine = auth_client

    def attempt(_):
        with TestClient(application_for(engine)) as concurrent:
            return signin(concurrent, "absent@example.com").status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(attempt, range(6)))
    assert sorted(codes) == [401] * 5 + [429]


def test_ip_throttle_and_registration_throttle(auth_client):
    client, _ = auth_client
    # La limite IP empêche de contourner la limite compte en changeant d'e-mail.
    for index in range(30):
        assert signin(client, f"absent{index}@example.com").status_code == 401
    assert signin(client, "another@example.com").status_code == 429
    signup(client)
    for _ in range(4):
        assert client.post("/api/v1/auth/register", json={
            "email": "alice@example.com", "password": PASSWORD,
        }).status_code == 409
    assert client.post("/api/v1/auth/register", json={
        "email": "alice@example.com", "password": PASSWORD,
    }).status_code == 429


def test_legacy_p02_data_preserved_by_migration(database):
    engine, config = database
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.downgrade(config, "0001")
        user_id, dream_id = uuid.uuid4(), uuid.uuid4()
        db.execute(text("INSERT INTO users(id, email) VALUES (:id, 'legacy@example.com')"),
                   {"id": user_id})
        db.execute(text("INSERT INTO dreams(id, user_id) VALUES (:id, :owner)"),
                   {"id": dream_id, "owner": user_id})
        command.upgrade(config, "head")
    with Session(engine) as db:
        assert db.get(User, user_id).password_hash is None
        assert db.get(Dream, dream_id).user_id == user_id


def test_real_database_dependency(auth_client, monkeypatch):
    _, engine = auth_client
    application = create_app()
    monkeypatch.setattr("backend.app.auth.make_engine", lambda: engine)
    with TestClient(application) as client:
        signup(client)
        assert signin(client).status_code == 200


def test_concurrent_registration_unique_account(auth_client):
    _, engine = auth_client

    def attempt(_):
        with TestClient(application_for(engine)) as client:
            return client.post("/api/v1/auth/register", json={
                "email": "concurrent@example.com", "password": PASSWORD,
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [201, 409]
    with Session(engine) as db:
        assert len(db.scalars(select(User)).all()) == 1


def test_rehash_after_successful_login(auth_client):
    from argon2 import PasswordHasher, Type

    client, engine = auth_client
    identifier = signup(client)
    with Session(engine) as db:
        db.get(User, uuid.UUID(identifier)).password_hash = PasswordHasher(
            time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID,
        ).hash(PASSWORD)
        db.commit()
    assert signin(client).status_code == 200
    with Session(engine) as db:
        assert "m=65536,t=3,p=1" in db.get(User, uuid.UUID(identifier)).password_hash


def test_media_and_job_routes_not_exposed(auth_client):
    client, engine = auth_client
    alice = signup(client)
    signup(client, "bob@example.com")
    seed_dream(engine, alice)
    headers = authorization(client, "bob@example.com")
    with Session(engine) as db:
        media_id, job_id = db.scalar(select(Media.id)), db.scalar(select(Job.id))
    assert client.get(f"/api/v1/media/{media_id}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).status_code == 404
