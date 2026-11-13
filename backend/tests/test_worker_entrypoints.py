"""Boucles CLI avec moteur, stockage et PostgreSQL simulés : aucun poids chargé."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app import (
    database,
    emotion_worker,
    image_provider,
    image_runner,
    image_worker,
    stt_worker,
)
from backend.app.services import image_execution
from backend.app.storage.local import LocalPrivateStorage


@pytest.fixture
def cli(monkeypatch, tmp_path):
    engine = SimpleNamespace(dispose=Mock())
    sessions, storage, provider = object(), object(), object()
    monkeypatch.setattr(database, "make_engine", lambda: engine)
    monkeypatch.setattr(database, "session_factory", lambda _: sessions)
    monkeypatch.setattr(stt_worker, "make_engine", lambda: engine)
    monkeypatch.setattr(stt_worker, "session_factory", lambda _: sessions)
    monkeypatch.setattr(stt_worker, "MediaService", lambda *args: storage)
    monkeypatch.setattr(LocalPrivateStorage, "from_environment", lambda: storage)
    monkeypatch.setattr(stt_worker.STTConfig, "from_environment", lambda: object())
    monkeypatch.setattr(stt_worker, "LocalWhisper", lambda _: provider)
    monkeypatch.setattr(image_provider, "SD15Config", lambda *args: object())
    monkeypatch.setattr(image_provider, "LocalStableDiffusion15", lambda *args: provider)
    monkeypatch.setattr(image_runner, "WatchedSD15Runner", lambda: object())
    monkeypatch.setattr(image_runner, "qualification_root", lambda: tmp_path)
    monkeypatch.setattr(image_runner, "gpu_slot", lambda: nullcontext(True))
    monkeypatch.setattr(emotion_worker, "LocalMDeberta", lambda *args: provider)
    monkeypatch.setattr(emotion_worker, "WatchedEmotionRunner", lambda: object())
    monkeypatch.setattr(emotion_worker, "worker_slot", lambda: nullcontext(True))
    monkeypatch.setattr(emotion_worker, "parameters", lambda: {})
    monkeypatch.setenv("EMOTION_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fiction@127.0.0.1:1/unused")
    return engine, sessions, storage, provider


@pytest.mark.parametrize("kind", ["stt", "image", "emotion"])
@pytest.mark.parametrize("scenario", ["success", "error", "interrupt", "idle_error_stop"])
def test_cli_once_or_controlled_loop(cli, monkeypatch, capsys, kind, scenario):
    engine, sessions, _, _ = cli
    modules = {"stt": stt_worker, "image": image_worker, "emotion": emotion_worker}
    target = {"stt": stt_worker, "image": image_execution, "emotion": emotion_worker}[kind]
    method = "work_once" if kind == "emotion" else "run_once"
    effects = {
        "success": [True], "error": [RuntimeError("FICTITIOUS_PRIVATE_FAILURE")],
        "interrupt": [KeyboardInterrupt()],
        "idle_error_stop": [False, RuntimeError("FICTITIOUS_PRIVATE_FAILURE"), KeyboardInterrupt()],
    }
    run = Mock(side_effect=effects[scenario])
    monkeypatch.setattr(target, method, run)
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(sys, "argv", ["worker", *([] if scenario == "idle_error_stop"
                                                 else ["--once"])])
    assert modules[kind].main() == (1 if scenario == "error" else 0)
    engine.dispose.assert_called_once()
    assert run.call_args.args[0] is sessions
    assert "FICTITIOUS_PRIVATE_FAILURE" not in capsys.readouterr().out
    assert sleeps == ([2, 5] if scenario == "idle_error_stop" else [])


@pytest.mark.parametrize("kind", ["image", "emotion"])
def test_busy_worker_does_not_process(cli, monkeypatch, kind):
    engine, *_ = cli
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    if kind == "image":
        monkeypatch.setattr(image_runner, "gpu_slot", lambda: nullcontext(False))
        run = Mock(side_effect=AssertionError("Aucun calcul attendu"))
        monkeypatch.setattr(image_execution, "run_once", run)
        assert image_worker.main() == 0
        engine.dispose.assert_called_once()
    else:
        monkeypatch.setattr(emotion_worker, "worker_slot", lambda: nullcontext(False))
        assert emotion_worker.main() == 2
        engine.dispose.assert_not_called()


@pytest.mark.parametrize("kind", ["stt", "emotion"])
def test_configuration_failure_releases_engine_without_details(cli, monkeypatch, capsys, kind):
    engine, *_ = cli
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])

    def unavailable(*args):
        raise RuntimeError("FICTITIOUS_PRIVATE_CONFIG")

    if kind == "stt":
        monkeypatch.setattr(stt_worker.STTConfig, "from_environment", unavailable)
        code = stt_worker.main()
    else:
        monkeypatch.setattr(emotion_worker, "parameters", unavailable)
        code = emotion_worker.main()
    assert code == 1
    engine.dispose.assert_called_once()
    assert "FICTITIOUS_PRIVATE_CONFIG" not in capsys.readouterr().out
