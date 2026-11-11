"""Décodage local isolé dans un processus borné en temps ; aucune opération réseau."""

import json
import sys
import wave
from pathlib import Path

import av

from backend.app.audio_types import MAX_SAMPLES, MAX_UPLOAD, SAMPLE_RATE

DEMUXERS = {"wav": "wav", "mp3": "mp3", "webm": "matroska", "ogg": "ogg", "mp4": "mov"}
CODECS = {
    "wav": {"pcm_u8", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le"},
    "mp3": {"mp3", "mp3float"}, "webm": {"opus", "vorbis"},
    "ogg": {"opus", "vorbis"}, "mp4": {"aac", "opus"},
}


def convert(source: Path, target: Path, media_format: str) -> dict:
    """Décode toutes les trames et écrit un WAV PCM mono 16 kHz, par blocs."""
    av.logging.set_level(av.logging.PANIC)
    if media_format not in DEMUXERS or not 0 < source.stat().st_size <= MAX_UPLOAD:
        raise ValueError
    expected = None
    with source.open("rb") as handle:
        signature = handle.read(16)
        accepted = {
            "wav": signature[:4] == b"RIFF" and signature[8:12] == b"WAVE",
            "mp3": signature[:3] == b"ID3" or (
                len(signature) >= 2 and signature[0] == 255 and signature[1] & 224 == 224
            ),
            "webm": signature[:4] == bytes.fromhex("1a45dfa3"),
            "ogg": signature[:4] == b"OggS", "mp4": signature[4:8] == b"ftyp",
        }
        if not accepted[media_format]:
            raise ValueError
    if media_format == "wav":
        with wave.open(str(source), "rb") as original:
            expected = original.getnframes()
    count, source_count = 0, 0
    with source.open("rb") as handle, av.open(
        handle, mode="r", format=DEMUXERS[media_format],
        options={"protocol_whitelist": "file", "enable_drefs": "0",
                 "use_absolute_path": "0", "err_detect": "explode",
                 "probesize": "1048576", "analyzeduration": "2000000"},
    ) as container:
        if len(container.streams) != 1 or len(container.streams.audio) != 1:
            raise ValueError
        stream = container.streams.audio[0]
        stream.codec_context.thread_count = 1
        stream.codec_context.options = {"err_detect": "explode"}
        if (stream.codec_context.name not in CODECS[media_format]
                or not 8000 <= stream.codec_context.sample_rate <= 192000
                or len(stream.codec_context.layout.channels) not in {1, 2}):
            raise ValueError
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)

            def write_frames(frames):
                nonlocal count
                for frame in frames:
                    count += frame.samples
                    if count > MAX_SAMPLES:
                        raise OverflowError
                    output.writeframesraw(bytes(frame.planes[0])[:frame.samples * 2])

            for frame in container.decode(stream):
                source_count += frame.samples
                if (frame.sample_rate <= 0 or frame.samples / frame.sample_rate > 10):
                    raise ValueError
                write_frames(resampler.resample(frame))
            write_frames(resampler.resample(None))
    if count == 0 or (expected is not None and source_count != expected):
        raise ValueError
    if target.stat().st_size > MAX_UPLOAD:
        raise OverflowError
    return {"duration_ms": (count * 1000 + SAMPLE_RATE - 1) // SAMPLE_RATE,
            "sample_rate_hz": SAMPLE_RATE, "channels": 1, "sample_count": count}


def main() -> int:
    """L'appelant fournit seulement des chemins temporaires générés et un format autorisé."""
    if len(sys.argv) != 4:
        return 2
    try:
        result = convert(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    except OverflowError:
        return 3
    except Exception:
        return 2  # ni traceback, ni sortie FFmpeg contenant un chemin ou du contenu
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
