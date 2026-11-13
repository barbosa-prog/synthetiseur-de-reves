"""P15 : diagnostics bornés, nettoyage et cohérence du verrou d'installation."""

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from backend.app.database import ROOT, session_factory
from scripts import local_demo


def test_http_recipe_with_real_postgres(database, monkeypatch, tmp_path):
    from backend.app.main import create_app

    engine, _ = database
    origin = "https://localhost:8443"
    monkeypatch.setenv("WEB_ORIGIN", origin)
    monkeypatch.setenv("API_DOCS_ENABLED", "0")
    monkeypatch.setenv("EMOTION_ENABLED", "0")
    monkeypatch.setenv("PRIVATE_MEDIA_ROOT", str(tmp_path / "private"))
    app = create_app()
    app.state.db_factory = session_factory(engine)
    # TestClient vérifie la recette HTTP/DB sans dépendre d'une interception TLS
    # du poste. Il ne constitue pas une validation du transport TLS réel.
    with TestClient(app, base_url=origin, follow_redirects=False) as client:
        local_demo.verify_application(client, origin, engine.url)


@pytest.mark.parametrize("arguments", [
    ["--stop-after", "-1"], ["--stop-after", "3601"], ["--check", "--stop-after", "1"],
])
def test_invalid_duration_is_rejected_before_starting_services(monkeypatch, arguments):
    monkeypatch.setattr(local_demo.sys, "argv", ["local_demo.py", *arguments])
    with pytest.raises(SystemExit) as error:
        local_demo.main()
    assert error.value.code == 2


def test_preparation_failure_never_exposes_subprocess_output(monkeypatch, capsys):
    monkeypatch.setattr(local_demo.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=b"PRIVATE_PASSWORD", stderr=b"PRIVATE_DATABASE_URL"))
    with pytest.raises(local_demo.DemoFailure, match="^alembic_check$"):
        local_demo.run_private(["fictional-command"], {}, "alembic_check")
    assert capsys.readouterr() == ("", "")


def test_postgres_is_stopped_even_if_server_stop_times_out(monkeypatch, tmp_path):
    calls = []

    class Server:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("fake-server", timeout)

    monkeypatch.setattr(local_demo, "postgres_command", lambda command: calls.append(command))
    monkeypatch.setattr(local_demo.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3))
    pg, data = tmp_path / "bin", tmp_path / "own-cluster"
    with pytest.raises(subprocess.TimeoutExpired):
        local_demo.stop_services(Server(), True, pg, data, 49100)
    assert calls == ["terminate", [str(pg / "pg_ctl.exe"), "-D", str(data),
                                  "-m", "fast", "-w", "stop"]]


def test_no_postgres_stop_when_cluster_was_not_started(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Un cluster non démarré ne doit pas être arrêté")

    monkeypatch.setattr(local_demo, "postgres_command", forbidden)
    local_demo.stop_services(None, False, Path("unused"), Path("unused"), 49100)


def test_windows_lock_covers_direct_dependencies_and_binary_driver():
    locked = {}
    for line in (ROOT / "requirements-windows-py312.lock").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        requirement, checksum = line.split(" --hash=sha256:")
        assert re.fullmatch(r"[a-f0-9]{64}", checksum)
        parsed = Requirement(requirement)
        locked[canonicalize_name(parsed.name)] = parsed
    for filename in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
            if not line or line.startswith(("#", "-r ")):
                continue
            parsed = Requirement(line)
            assert locked[canonicalize_name(parsed.name)].specifier == parsed.specifier
    assert locked["psycopg-binary"].specifier == locked["psycopg"].specifier
    assert not ({"torch", "transformers", "diffusers", "faster-whisper", "huggingface-hub"}
                & locked.keys())
