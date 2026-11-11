"""Pont PyAV 19 vers l'entrée numérique Whisper, sans décodeur tiers incompatible."""

import io

import av
import numpy as np

from backend.app.audio_types import MAX_SAMPLES, MAX_UPLOAD, SAMPLE_RATE


def decode_private_wav(audio: bytes) -> np.ndarray:
    """Décode le WAV P04 en mono float32 16 kHz, avec les limites P04 inchangées.

    faster-whisper 1.2.1 passe metadata_errors à av.open, retiré dans PyAV 19.
    Son API accepte aussi un ndarray : le décodage local évite cet appel sans
    modifier une bibliothèque, télécharger quoi que ce soit ou masquer une erreur.
    """
    if not 0 < len(audio) <= MAX_UPLOAD or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise ValueError("Audio WAV invalide")
    buffer = io.BytesIO()
    count = 0
    with av.open(io.BytesIO(audio), mode="r", format="wav", options={
        "protocol_whitelist": "file", "enable_drefs": "0", "use_absolute_path": "0",
        "err_detect": "explode",
    }) as container:
        if len(container.streams) != 1 or len(container.streams.audio) != 1:
            raise ValueError("Audio WAV invalide")
        stream = container.streams.audio[0]
        stream.codec_context.thread_count = 1
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

        def append(frames):
            nonlocal count
            for frame in frames:
                count += frame.samples
                if count > MAX_SAMPLES:
                    raise ValueError("Durée audio dépassée")
                buffer.write(bytes(frame.planes[0])[:frame.samples * 2])

        for frame in container.decode(stream):
            frame.pts = None
            append(resampler.resample(frame))
        append(resampler.resample(None))
    if count == 0:
        raise ValueError("Audio vide")
    return np.frombuffer(buffer.getvalue(), dtype="<i2").astype(np.float32) / 32768.0
