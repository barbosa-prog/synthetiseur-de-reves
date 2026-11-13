"""Réception ASGI progressive, sans base de données et avec données fictives."""

import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.app import http_guard
from backend.app.main import create_app


def exchange(chunks, *, path="/api/v1/_p12", headers=(), delay=0, seconds=1):
    delivered, sent = [], []

    async def app(scope, receive, send):
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        delivered.append(bytes(body))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def run():
        source = iter(chunks)

        async def receive():
            await asyncio.sleep(delay)
            return next(source)

        async def send(message):
            sent.append(message)

        await http_guard.HTTPGuard(app)(
            {"type": "http", "method": "POST", "path": path, "headers": list(headers)},
            receive, send)

    asyncio.run(asyncio.wait_for(run(), timeout=seconds))
    return sent[0]["status"], delivered, sent


def chunk(body=b"", more=False):
    return {"type": "http.request", "body": body, "more_body": more}


@pytest.mark.parametrize("path,limit", [
    ("/api/v1/dreams/example/transcript", 256*1024),
    ("/connexion", 8192), ("/inscription", 8192),
    ("/reves/example/recit", 256*1024), ("/unknown", 8192),
    ("/web/audio", 15*1024**2), ("/api/v1/dreams/audio", 15*1024**2),
])
def test_progressive_oversize_is_rejected_before_delivery(path, limit):
    status, delivered, _ = exchange([chunk(b"x"*limit, True), chunk(b"x")], path=path)
    assert status == 413 and not delivered


@pytest.mark.parametrize("declared,body,status", [
    (None, b"abc", 200), (b"3", b"abc", 200), (b"2", b"abc", 400),
    (b"4", b"abc", 400), (b"-1", b"", 400), (b"invalid", b"", 400),
    (b"9"*30, b"", 400), (b"999999", b"", 413),
])
def test_declared_length_is_never_trusted(declared, body, status):
    headers = [] if declared is None else [(b"content-length", declared)]
    actual, delivered, _ = exchange([chunk(body)], headers=headers)
    assert actual == status
    assert delivered == ([body] if status == 200 else [])


@pytest.mark.parametrize("headers,status", [
    ([(b"content-length", b"0"), (b"content-length", b"0")], 400),
    ([(b"content-length", b"0"), (b"transfer-encoding", b"chunked")], 400),
    ([(b"content-encoding", b"gzip")], 415),
])
def test_ambiguous_or_encoded_bodies_are_refused(headers, status):
    assert exchange([], headers=headers)[0] == status


@pytest.mark.parametrize("streaming", [False, True])
def test_slow_and_interrupted_streams_never_reach_business(monkeypatch, streaming):
    monkeypatch.setattr(http_guard, "policy", lambda _: (8192, .01, streaming))
    assert exchange([chunk(b"fictitious")], delay=.03)[0] == 408
    status, delivered, _ = exchange([chunk(b"x", True), {"type": "http.disconnect"}])
    assert status == 408 and not delivered


def test_many_small_chunks_and_exact_limit():
    status, delivered, _ = exchange([chunk(b"x"*1024, i < 7) for i in range(8)],
                                    path="/connexion")
    assert status == 200 and delivered == [b"x"*8192]


def test_audio_authentication_can_refuse_without_consuming_body():
    async def run():
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def receive():
            pytest.fail("Le corps audio ne doit pas etre lu avant le refus")

        async def send(message):
            pass

        await http_guard.HTTPGuard(app)({"type": "http", "path": "/web/audio",
                                        "headers": []}, receive, send)
    asyncio.run(run())


def test_fastapi_json_and_form_errors_are_generic():
    app = create_app()

    @app.post("/api/v1/_p12/echo")
    async def echo(request: Request):
        return await request.json()

    with TestClient(app) as client:
        response = client.post("/api/v1/_p12/echo", content=json.dumps({"a": "x"*262144}))
        assert response.status_code == 413
        assert "xxxxx" not in response.text
        response = client.post("/api/v1/_p12/echo", json={"a": "fictitious"})
        assert response.json() == {"a": "fictitious"}
        response = client.post("https://localhost:8443/connexion", content=b"x"*8193)
        assert response.status_code == 413


def test_stream_limit_survives_starlette_exception_wrapping(monkeypatch):
    monkeypatch.setattr(http_guard, "policy", lambda _: (4, 1, True))
    app = FastAPI()

    @app.middleware("http")
    async def forwarding(request, call_next):
        return await call_next(request)

    @app.post("/stream")
    async def read(request: Request):
        async for _ in request.stream():
            pass
        return {"saved": True}

    app.add_middleware(http_guard.HTTPGuard)
    with TestClient(app) as client:
        response = client.post("/stream", content=iter([b"xxx", b"xxx"]))
    assert response.status_code == 413
