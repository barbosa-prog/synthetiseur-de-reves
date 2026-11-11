"""Signaux sinusoïdaux synthétiques, réellement encodés en local ; aucune voix personnelle."""

import io
import math
import struct
import wave
from fractions import Fraction

import av


def audio_sample(media_format="wav") -> bytes:
    """Produit environ une seconde de son à 440 Hz, sans fichier externe."""
    if media_format == "wav":
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"".join(
                struct.pack("<h", int(1000 * math.sin(i * math.tau * 440 / 16000)))
                for i in range(16000)
            ))
        return buffer.getvalue()
    codec, container_format, rate = {
        "mp3": ("libmp3lame", "mp3", 16000),
        "webm": ("libopus", "webm", 48000),
        "ogg": ("libopus", "ogg", 48000),
        "mp4": ("aac", "mp4", 44100),
    }[media_format]
    buffer = io.BytesIO()
    with av.open(buffer, "w", format=container_format) as output:
        stream = output.add_stream(codec, rate=rate)
        stream.layout = "mono"
        for start in range(0, rate, 1024):
            count = min(1024, rate - start)
            frame = av.AudioFrame(format="s16", layout="mono", samples=count)
            frame.sample_rate, frame.pts, frame.time_base = rate, start, Fraction(1, rate)
            frame.planes[0].update(b"".join(
                struct.pack("<h", int(1000 * math.sin(i * math.tau * 440 / rate)))
                for i in range(start, start + count)
            ))
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    return buffer.getvalue()
