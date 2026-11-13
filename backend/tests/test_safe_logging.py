"""Vrais logs Uvicorn sur serveur éphémère sans PostgreSQL ni fournisseur IA."""

import json
import logging
import os
import socket
import subprocess
import sys
import time

import httpx

from backend.app.database import ROOT
from backend.app.safe_logging import install_safe_logging


def test_logger_whitelist_drops_arguments_exceptions_and_stack(caplog):
    install_safe_logging()
    with caplog.at_level(logging.WARNING):
        try:
            raise RuntimeError("FICTITIOUS_STORY_MARKER")
        except RuntimeError:
            logging.getLogger("thirdparty").exception("SECRET_%s", "FICTITIOUS_TOKEN_MARKER",
                                                      stack_info=True)
    assert "diagnostic_redacted" in caplog.text
    assert "FICTITIOUS" not in caplog.text and "SECRET" not in caplog.text
    record = caplog.records[-1]
    assert record.exc_info is record.exc_text is record.stack_info is None


def test_private_child_stdout_is_not_a_log(caplog):
    result = subprocess.run([sys.executable, "-c",
                             "print('{\"text\":\"FICTITIOUS_PIPE_MARKER\"}')"],
                            capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout)["text"] == "FICTITIOUS_PIPE_MARKER"
    assert "FICTITIOUS_PIPE_MARKER" not in caplog.text


def test_real_uvicorn_logs_never_include_private_markers(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    assert port != 5434
    env = {**os.environ, "EMOTION_ENABLED": "0",
           "DATABASE_URL": "postgresql+psycopg://fictitious@127.0.0.1:1/p12_unused"}
    log = tmp_path / "server.log"
    with log.open("wb") as stream:
        server = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "backend.tests.p12_server_fixture:app",
            "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers",
            "--access-log", "--log-level", "debug",
        ], cwd=ROOT, env=env, stdout=stream, stderr=stream)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                              timeout=3) as client:
                for _ in range(100):
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise AssertionError("Serveur fictif non disponible")
                response = client.post(
                    "/api/v1/_p12/crash/FICTITIOUS_PATH_MARKER?q=FICTITIOUS_QUERY_MARKER",
                    json={"story": "FICTITIOUS_STORY_MARKER"},
                    headers={"Authorization": "Bearer FICTITIOUS_TOKEN_MARKER",
                             "Cookie": "session=FICTITIOUS_COOKIE_MARKER",
                             "X-API-Key": "FICTITIOUS_KEY_MARKER"})
                assert response.status_code == 500
                assert "FICTITIOUS" not in response.text
                try:
                    partial = client.get("/api/v1/_p12/partial")
                except httpx.RemoteProtocolError:
                    pass
                else:
                    assert partial.status_code == 200
                assert client.get("/api/v1/health").status_code == 200
        finally:
            server.terminate()
            server.wait(timeout=15)
    output = log.read_text(encoding="utf-8", errors="replace")
    assert "request_failed" in output and "diagnostic_redacted" in output
    assert "response_interrupted" in output
    assert "FICTITIOUS" not in output
    assert "Traceback" not in output and "Logging error" not in output
