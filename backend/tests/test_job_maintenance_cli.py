"""Garde-fous CLI P11, sans connexion PostgreSQL ni moteur IA."""

import sys

import pytest

from scripts import job_maintenance as cli


@pytest.mark.parametrize("url,confirmation", [
    (None, "temporary"),
    ("sqlite:///fiction.db", "fiction"),
    ("postgresql+psycopg://localhost/temporary", "other"),
])
def test_cli_refuses_missing_or_unconfirmed_target(monkeypatch, url, confirmation, capsys):
    monkeypatch.setattr(sys, "argv", ["maintenance", "--apply", "--confirm-database", confirmation])
    if url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(cli, "make_engine", lambda *_: pytest.fail("Connexion interdite"))
    assert cli.main() == 1
    assert "postgresql" not in capsys.readouterr().out


@pytest.mark.parametrize("apply", [False, True])
def test_cli_inventory_default_and_explicit_apply_release_engine(monkeypatch, apply, capsys):
    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/fiction_temporary")
    monkeypatch.setattr(sys, "argv", ["maintenance"] + (
        ["--apply", "--confirm-database", "fiction_temporary"] if apply else []))
    monkeypatch.setattr(cli, "make_engine", lambda _: engine)
    monkeypatch.setattr(cli, "session_factory", lambda _: object())

    def maintain(_sessions, **options):
        assert options["apply"] is apply
        assert options["policy"].queued_seconds == 1800
        assert options["policy"].recovery_interval_seconds == 5
        return dict(candidates=1, failed=int(apply), deferred=0)

    monkeypatch.setattr(cli, "maintain", maintain)
    assert cli.main() == 0 and engine.disposed
    assert ('"mode": "apply"' if apply else '"mode": "inventory"') in capsys.readouterr().out
