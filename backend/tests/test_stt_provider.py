"""Contrat local, limites et absence de réseau ; aucun modèle chargé."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from backend.app import stt_provider as stt


def test_memory_guard(monkeypatch):
    monkeypatch.setattr(stt, "available_memory_mb", lambda: 900)
    with pytest.raises(stt.STTError, match="insufficient_memory"):
        stt.require_memory(3072)
    monkeypatch.setattr(stt, "available_memory_mb", lambda: 4096)
    stt.require_memory(3072)


def test_missing_model_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "require_memory", lambda _: None)
    with pytest.raises(stt.STTError, match="model_unavailable"):
        stt.LocalWhisper(stt.STTConfig("faster-whisper", tmp_path / "absent")).transcribe(b"audio")


def test_subprocess_timeout_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "require_memory", lambda _: None)

    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired("private", 30)

    monkeypatch.setattr(stt.subprocess, "run", expire)
    with pytest.raises(stt.STTError, match="timeout"):
        stt.LocalWhisper(stt.STTConfig("faster-whisper", tmp_path, 30)).transcribe(b"audio")


@pytest.mark.parametrize("output,code", [(b"invalid", 0), (b"{}", 0), (b"", 1),
                                        (b"x" * 262145, 0)])
def test_malformed_provider_response(tmp_path, monkeypatch, output, code):
    monkeypatch.setattr(stt, "require_memory", lambda _: None)
    monkeypatch.setattr(stt.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=code, stdout=output,
    ))
    with pytest.raises(stt.STTError, match="provider_failed"):
        stt.LocalWhisper(stt.STTConfig("faster-whisper", tmp_path)).transcribe(b"audio")


def test_adapter_success(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "require_memory", lambda _: None)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"text": "Récit fictif"}).encode())

    monkeypatch.setattr(stt.subprocess, "run", run)
    provider = stt.LocalWhisper(stt.STTConfig("faster-whisper", tmp_path, 30))
    assert provider.transcribe(b"audio") == "Récit fictif"
    assert calls[0][1]["input"] == b"audio" and calls[0][1]["timeout"] == 30
    assert "http" not in str(calls[0][0])


def test_unknown_engine_is_rejected(monkeypatch):
    monkeypatch.setenv("STT_ENGINE", "unknown")
    with pytest.raises(stt.STTError, match="configuration"):
        stt.STTConfig.from_environment()
