"""Stockage réel isolé : aucun média personnel ni répertoire privé existant."""

import io
import os
import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image

from backend.app.database import ROOT
from backend.app.storage.local import (
    MAX_AUDIO,
    MAX_IMAGE,
    InvalidMedia,
    LocalPrivateStorage,
    StorageError,
    new_key,
)


def image_bytes(media_format="png"):
    stream = io.BytesIO()
    Image.new("RGB", (4, 4), "purple").save(stream, format=media_format)
    return stream.getvalue()


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 160)
    return stream.getvalue()


@pytest.mark.parametrize("media_format", ["png", "jpeg", "webp", "wav"])
def test_write_read_restart_delete(tmp_path, media_format):
    store = LocalPrivateStorage(tmp_path / "private")
    payload = wav_bytes() if media_format == "wav" else image_bytes(media_format)
    key = new_key()
    kind = "audio" if media_format == "wav" else "image"
    stored = store.write(io.BytesIO(payload), key=key, kind=kind, media_format=media_format)
    assert stored.size == len(payload) and len(key) == 64
    restarted = LocalPrivateStorage(tmp_path / "private")
    with restarted.open(key) as stream:
        assert stream.read() == payload
    assert [entry.key for entry in restarted.inventory()] == [key]
    restarted.delete(key)
    restarted.delete(key)
    assert restarted.inventory() == []


@pytest.mark.parametrize("key", ["../secret", "..\\secret", "/etc/passwd", "C:\\secret",
                                "x:y", "a" * 63, "a" * 64 + ".png", "A" * 64, "\x00"])
def test_dangerous_keys_refused(tmp_path, key):
    store = LocalPrivateStorage(tmp_path / "private")
    for operation in [store.open, store.delete]:
        with pytest.raises(StorageError):
            operation(key)


@pytest.mark.parametrize("filename", ["../image.png", "..\\image.png", "C:\\x.png",
                                     "image.png:secret", "CON.png", "image.png ",
                                     "image.exe", "image\x00.png"])
def test_malicious_names_refused(tmp_path, filename):
    store = LocalPrivateStorage(tmp_path / "private")
    with pytest.raises(InvalidMedia):
        store.write(io.BytesIO(image_bytes()), key=new_key(), kind="image",
                    media_format="png", filename=filename)
    assert not store.root.exists()


@pytest.mark.parametrize("payload,kind,media_format", [
    (b"", "audio", "wav"), (b"not a wave", "audio", "wav"),
    (b"ID3 not a real MP3", "audio", "mp3"),
    (b"<svg><script>alert(1)</script></svg>", "image", "svg"),
    (b"not an image", "image", "png"),
    (image_bytes(), "audio", "png"), (image_bytes(), "image", "jpeg"),
    (b"x" * (MAX_IMAGE + 1), "image", "png"),
    (image_bytes()[:20], "image", "png"),
])
def test_invalid_content_and_limits(tmp_path, payload, kind, media_format):
    store = LocalPrivateStorage(tmp_path / "private")
    with pytest.raises(InvalidMedia):
        store.write(io.BytesIO(payload), key=new_key(), kind=kind, media_format=media_format)
    assert not store.root.exists()


def test_atomic_failure_and_collision_preserve_original(tmp_path, monkeypatch):
    store = LocalPrivateStorage(tmp_path / "private")
    key = new_key()
    store.write(io.BytesIO(image_bytes()), key=key, kind="image", media_format="png")
    with pytest.raises(StorageError):
        store.write(io.BytesIO(image_bytes()), key=key, kind="image", media_format="png")
    with store.open(key) as stream:
        assert stream.read() == image_bytes()
    assert len(store.inventory()) == 1

    def fail(*args):
        raise OSError("fictitious filesystem failure")

    monkeypatch.setattr("backend.app.storage.local.os.fsync", fail)
    with pytest.raises(StorageError):
        store.write(io.BytesIO(image_bytes()), key=new_key(), kind="image", media_format="png")
    assert len(store.inventory()) == 1


def test_existing_staging_not_removed_on_collision(tmp_path):
    store = LocalPrivateStorage(tmp_path / "private")
    store.root.mkdir()
    key = new_key()
    staged = store.root / f".{key}.tmp"
    staged.write_bytes(b"another active write")
    with pytest.raises(StorageError):
        store.write(io.BytesIO(image_bytes()), key=key, kind="image", media_format="png")
    assert staged.read_bytes() == b"another active write"


@pytest.mark.parametrize("path", [ROOT / "private_media", ROOT / "backend/app/web/static/private"])
def test_repository_root_refused(path):
    with pytest.raises(StorageError):
        LocalPrivateStorage(path)


def test_onedrive_relative_and_root_junction_refused(tmp_path):
    for path in [tmp_path / "OneDrive/private", Path("relative")]:
        with pytest.raises(StorageError):
            LocalPrivateStorage(path)
    target, junction = tmp_path / "elsewhere", tmp_path / "junction"
    target.mkdir()
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                                capture_output=True)
        assert result.returncode == 0
    else:
        junction.symlink_to(target, target_is_directory=True)
    with pytest.raises(StorageError):
        LocalPrivateStorage(junction / "private")


def test_hardlink_cannot_expose_external_file(tmp_path):
    store = LocalPrivateStorage(tmp_path / "private")
    initial = new_key()
    store.write(io.BytesIO(image_bytes()), key=initial, kind="image", media_format="png")
    store.delete(initial)
    external = tmp_path / "external"
    external.write_bytes(b"fictitious external data")
    key = new_key()
    os.link(external, store.root / key)
    with pytest.raises(StorageError):
        store.open(key)
    store.delete(key)
    assert external.read_bytes() == b"fictitious external data"


def test_mp3_structure_and_audio_limit(tmp_path):
    store = LocalPrivateStorage(tmp_path / "private")
    # Trames MPEG synthétiques : valide le parseur de structure, pas un décodage sonore complet.
    payload = (bytes.fromhex("fffb9000") + bytes(413)) * 10
    stored = store.write(io.BytesIO(payload), key=new_key(), kind="audio", media_format="mp3")
    assert stored.media_type == "audio/mpeg"
    with pytest.raises(InvalidMedia):
        store.write(io.BytesIO(bytes(MAX_AUDIO + 1)), key=new_key(),
                    kind="audio", media_format="wav")


def test_configuration_and_inventory_are_lazy(tmp_path, monkeypatch):
    root = tmp_path / "private"
    monkeypatch.setenv("PRIVATE_MEDIA_ROOT", str(root))
    storage = LocalPrivateStorage.from_environment()
    assert storage.root == root and storage.inventory() == [] and not root.exists()
    monkeypatch.setenv("PRIVATE_MEDIA_ROOT", str(tmp_path / "OneDrive/private"))
    with pytest.raises(StorageError):
        LocalPrivateStorage.from_environment()


def test_arbitrary_existing_directory_is_never_adopted(tmp_path):
    existing = tmp_path / "existing_data"
    existing.mkdir()
    original = existing / ("a" * 64)
    original.write_bytes(b"fictitious existing data")
    with pytest.raises(StorageError):
        LocalPrivateStorage(existing)
    assert original.read_bytes() == b"fictitious existing data"
