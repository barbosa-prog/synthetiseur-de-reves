"""Décodage réel et échecs de réception bornée, sans base ni données personnelles."""

import asyncio
import subprocess
import wave

import pytest
from starlette.requests import ClientDisconnect

from backend.app.audio_types import MAX_UPLOAD, AudioError
from backend.app.audio_worker import convert
from backend.app.services.audio import normalize, receive_audio
from backend.tests.audio_fixtures import audio_sample


@pytest.mark.parametrize("media_format", ["wav", "mp3", "webm", "ogg", "mp4"])
def test_real_decode_and_normalization(tmp_path, media_format):
    source, target = tmp_path / "input", tmp_path / "output.wav"
    source.write_bytes(audio_sample(media_format))
    metadata = normalize(source, target, media_format)
    assert 900 <= metadata["duration_ms"] <= 1200
    assert metadata["sample_rate_hz"] == 16000 and metadata["channels"] == 1
    with wave.open(str(target), "rb") as audio:
        assert audio.getnchannels() == 1 and audio.getframerate() == 16000
        assert audio.getsampwidth() == 2 and audio.getnframes() == metadata["sample_count"]


@pytest.mark.parametrize("payload,media_format", [
    (b"not an audio", "wav"), (b"ID3notmpeg", "mp3"), (b"<script>bad</script>", "webm"),
    (audio_sample("wav")[:-100], "wav"), (audio_sample("mp3"), "wav"),
])
def test_forged_or_truncated_input(tmp_path, payload, media_format):
    source, target = tmp_path / "input", tmp_path / "output.wav"
    source.write_bytes(payload)
    with pytest.raises(AudioError):
        normalize(source, target, media_format)


def test_duration_is_measured_and_limited(tmp_path, monkeypatch):
    source, target = tmp_path / "input", tmp_path / "output.wav"
    source.write_bytes(audio_sample())
    monkeypatch.setattr("backend.app.audio_worker.MAX_SAMPLES", 100)
    with pytest.raises(OverflowError):
        convert(source, target, "wav")


def test_decode_timeout_is_generic(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("decoder", 20)

    monkeypatch.setattr("backend.app.services.audio.subprocess.run", timeout)
    with pytest.raises(AudioError, match="20 secondes"):
        normalize(tmp_path / "input", tmp_path / "output", "wav")


@pytest.mark.parametrize("case", ["disconnect", "overflow", "empty", "incomplete"])
def test_interrupted_or_invalid_upload_leaves_no_temporary_file(tmp_path, monkeypatch, case):
    monkeypatch.setattr("backend.app.services.audio.tempfile.gettempdir", lambda: str(tmp_path))

    class Request:
        headers = {"x-audio-format": "wav", **({"content-length": "999"}
                                              if case == "incomplete" else {})}

        async def stream(self):
            if case == "disconnect":
                yield b"RIFF"
                raise ClientDisconnect
            if case == "overflow":
                for _ in range(241):
                    yield bytes(65536)
            elif case != "empty":
                yield b"RIFF"

    with pytest.raises(AudioError):
        asyncio.run(receive_audio(Request(), None, None))
    assert list(tmp_path.iterdir()) == []


def test_exact_15_mib_wav_is_decoded(tmp_path):
    # Un WAV PCM exactement à la limite, durée < 8 minutes, sans grosse allocation de décodage.
    source, target = tmp_path / "input", tmp_path / "output.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(bytes(MAX_UPLOAD - 44))
    assert source.stat().st_size == MAX_UPLOAD
    assert normalize(source, target, "wav")["duration_ms"] > 100000


def test_real_duration_over_eight_minutes_is_rejected(tmp_path):
    source, target = tmp_path / "input", tmp_path / "output.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(481 * 16000 * 2))
    assert source.stat().st_size < MAX_UPLOAD
    with pytest.raises(AudioError, match="8 minutes"):
        normalize(source, target, "wav")
