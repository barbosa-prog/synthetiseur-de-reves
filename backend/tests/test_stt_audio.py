"""Décodage réel PyAV, moteur fictif ; aucun poids ni appel réseau."""

import io
import wave

import av
import pytest

np = pytest.importorskip("numpy", reason="Dépendances STT optionnelles absentes")

from backend.app.stt_audio import decode_private_wav  # noqa: E402
from backend.tests.audio_fixtures import audio_sample  # noqa: E402


def test_p04_wav_to_float32():
    samples = decode_private_wav(audio_sample())
    assert samples.dtype == np.float32 and samples.shape == (16000,)
    assert np.isfinite(samples).all() and abs(samples).max() <= 1
    assert abs(samples).max() > 0


def test_windows_tts_rate_is_resampled():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x10" * 22050)
    assert decode_private_wav(stream.getvalue()).shape == (16000,)


@pytest.mark.parametrize("payload", [b"", b"invalid", b"RIFF1234WAVE", b"x" * 15728641])
def test_invalid_wav_refused(payload):
    with pytest.raises((ValueError, av.error.FFmpegError)):
        decode_private_wav(payload)


def test_duration_limit_is_preserved(monkeypatch):
    monkeypatch.setattr("backend.app.stt_audio.MAX_SAMPLES", 100)
    with pytest.raises(ValueError, match="Durée"):
        decode_private_wav(audio_sample())
