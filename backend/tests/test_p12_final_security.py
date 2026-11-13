"""Recette sans modèle : ressources publiques, documentation et chargement hors ligne."""

import ast
import io
import json
import os
import platform
import re
import runpy
import socket
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import stt_provider
from backend.app.database import ROOT
from backend.app.emotion_config import parameters
from backend.app.image_provider import ImageError, ImageRequest, LocalStableDiffusion15, SD15Config
from backend.app.main import create_app
from backend.app.offline import OFFLINE_FLAGS, inference_environment


@pytest.fixture
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Acces reseau interdit dans ce test de chargeur")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def test_child_environment_is_offline_and_does_not_inherit_server_secrets(monkeypatch):
    for key in ["DATABASE_URL", "TEST_DATABASE_URL", "POSTGRES_PASSWORD", "PGPASSWORD",
                "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "CUSTOM_API_KEY", "CUSTOM_SECRET",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "PGPASSFILE", "POSTGRES_USER"]:
        monkeypatch.setenv(key, "FICTITIOUS_ENV_SECRET")
    monkeypatch.setenv("LOCALAPPDATA", "FICTITIOUS_LOCAL_DIRECTORY")
    for key in OFFLINE_FLAGS:
        monkeypatch.setenv(key, "0")
    env = inference_environment()
    assert not any(value == "FICTITIOUS_ENV_SECRET" for value in env.values())
    assert env["LOCALAPPDATA"] == "FICTITIOUS_LOCAL_DIRECTORY"
    assert all(env[key] == "1" for key in OFFLINE_FLAGS)
    assert os.environ["DATABASE_URL"] == "FICTITIOUS_ENV_SECRET"


def test_stt_loader_is_local_and_fails_safely_without_weights(monkeypatch, tmp_path, no_network,
                                                            capsys):
    captured = []

    def loader(path, **kwargs):
        captured.append(kwargs)
        assert kwargs["local_files_only"] is True
        assert all(os.environ[key] == "1" for key in OFFLINE_FLAGS)
        raise FileNotFoundError("FICTITIOUS_MISSING_WEIGHTS")

    for key in OFFLINE_FLAGS:
        monkeypatch.setenv(key, "0")
    monkeypatch.setattr(stt_provider, "require_memory", lambda _: None)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=loader))
    monkeypatch.setattr(sys, "argv", ["stt", str(tmp_path)])
    stt_provider.main()
    output = capsys.readouterr().out
    assert json.loads(output) == {"error": "provider_failed"}
    assert len(captured) == 1 and "FICTITIOUS" not in output


def test_stt_missing_directory_never_launches_child(monkeypatch, tmp_path, no_network):
    monkeypatch.setattr(stt_provider, "require_memory", lambda _: None)
    monkeypatch.setattr(stt_provider.subprocess, "run",
                        lambda *a, **k: pytest.fail("Enfant interdit"))
    with pytest.raises(stt_provider.STTError, match="model_unavailable"):
        stt_provider.LocalWhisper(stt_provider.STTConfig(
            "faster-whisper", tmp_path / "absent")).transcribe(b"fictitious")


def test_image_adapter_missing_model_does_not_launch_runner(tmp_path, no_network):
    class Never:
        def run(self, *args):
            pytest.fail("Runner interdit sans modele local")
    with pytest.raises(ImageError, match="model_unavailable"):
        LocalStableDiffusion15(SD15Config(tmp_path), Never()).generate(ImageRequest(
            description="Foret fictive", text_version=1, description_version=1))


def test_gpu_loader_flags_with_stub_only(monkeypatch, tmp_path, no_network):
    directory = tmp_path / "private-image-p12"
    directory.mkdir()
    (directory / "request.json").write_text(json.dumps({
        "model_path": str(tmp_path / "absent"), "description": "FICTITIOUS_VISUAL", "seed": 42,
    }))
    captured, events = [], []

    def loader(path, **kwargs):
        captured.append(kwargs)
        assert kwargs["local_files_only"] is True and kwargs["use_safetensors"] is True
        raise FileNotFoundError("FICTITIOUS_MISSING_WEIGHTS")

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        float16="float16", OutOfMemoryError=type("FakeOOM", (Exception,), {})))
    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(
        StableDiffusionPipeline=SimpleNamespace(from_pretrained=loader)))
    monkeypatch.setitem(sys.modules, "common", SimpleNamespace(
        paths=lambda: (tmp_path, None), ram_mib=lambda: 8192))
    monkeypatch.setitem(sys.modules, "cpu_mini", SimpleNamespace(
        emit=lambda name, **values: events.append((name, values))))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"CPU_ONLY\n")))
    monkeypatch.setattr(sys, "argv", ["gpu-stub", str(directory)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(ROOT / "qualification/p07/image_job_gpu.py"), run_name="__main__")
    assert error.value.code == 1 and len(captured) == 1
    assert events[-1][0] == "application_image_failed"
    assert "FICTITIOUS" not in json.dumps(events) and not (directory / "output.png").exists()


def test_emotion_missing_model_exits_before_importing_ai(monkeypatch, tmp_path, no_network):
    import importlib.metadata
    config = {**parameters(), "inference_enabled": True}
    for key in [*OFFLINE_FLAGS, "CUDA_VISIBLE_DEVICES", "TOKENIZERS_PARALLELISM",
                "OMP_NUM_THREADS", "MKL_NUM_THREADS"]:
        monkeypatch.setenv(key, "0")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # Le test vise l'absence de poids APRÈS validation de l'environnement qualifié.
    # Le correctif Python du runner peut différer de celui du venv IA qualifié.
    monkeypatch.setattr(platform, "python_version", lambda: config["python"])
    monkeypatch.setattr(importlib.metadata, "version", lambda name: config["dependencies"][name])
    payload = dict(configuration=config, request={"text": "Recit fictif"})
    monkeypatch.setattr(sys, "stdin",
                        SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode())))
    module = runpy.run_path(str(ROOT / "scripts/emotion_cpu_child.py"), run_name="p12_child")
    assert module["main"]() == {"error": "model_unavailable"}


def test_stt_missing_numpy_fails_before_loader_without_private_output(monkeypatch, tmp_path,
                                                                   no_network, capsys):
    """Reproduit le runner sans NumPy, sans désinstaller quoi que ce soit."""
    import builtins

    captured = []
    original_import = builtins.__import__

    def without_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ModuleNotFoundError("FICTITIOUS_MISSING_NUMPY")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "backend.app.stt_audio", raising=False)
    monkeypatch.setattr(builtins, "__import__", without_numpy)
    monkeypatch.setattr(stt_provider, "require_memory", lambda _: None)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(
        WhisperModel=lambda *a, **k: captured.append(True)))
    monkeypatch.setattr(sys, "argv", ["stt", str(tmp_path)])
    stt_provider.main()
    output = capsys.readouterr().out
    assert json.loads(output) == {"error": "provider_failed"}
    assert captured == [] and "FICTITIOUS" not in output


@pytest.mark.parametrize("mismatch", ["python", "dependency"])
def test_emotion_rejects_unqualified_environment_before_model_access(monkeypatch, no_network,
                                                                    mismatch):
    """Conserve le contrôle exact des versions ; aucune dépendance IA importée."""
    import importlib.metadata
    from pathlib import Path

    config = {**parameters(), "inference_enabled": True}
    monkeypatch.setattr(platform, "python_version", lambda:
                        "3.12.0" if mismatch == "python" else config["python"])
    monkeypatch.setattr(importlib.metadata, "version", lambda name:
                        "unqualified" if mismatch == "dependency"
                        else config["dependencies"][name])
    payload = {"configuration": config, "request": {"text": "Récit fictif"}}
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(
        buffer=io.BytesIO(json.dumps(payload).encode())))
    module = runpy.run_path(str(ROOT / "scripts/emotion_cpu_child.py"), run_name="p12_child")
    with monkeypatch.context() as guard:
        guard.setattr(Path, "is_dir", lambda _: pytest.fail("Lecture du modèle interdite"))
        assert module["main"]() == {"error": "configuration"}


@pytest.mark.parametrize("file", ["scripts/emotion_cpu_child.py",
                                   "qualification/p07/image_job_gpu.py"])
def test_local_only_loader_options_are_explicit_in_each_child(file):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "from_pretrained"]
    assert calls
    for call in calls:
        values = {kw.arg: kw.value for kw in call.keywords}
        assert isinstance(values["local_files_only"], ast.Constant)
        assert values["local_files_only"].value is True
        if "trust_remote_code" in values:
            assert values["trust_remote_code"].value is False


@pytest.mark.parametrize("setting", ["0", "1"])
def test_docs_opt_out_keeps_openapi_and_contains_no_private_resources(monkeypatch, setting):
    monkeypatch.setenv("API_DOCS_ENABLED", setting)
    with TestClient(create_app()) as client:
        for path in ["/api/v1/docs", "/api/v1/redoc", "/api/v1/docs/oauth2-redirect"]:
            response = client.get(path)
            assert response.status_code == (200 if setting == "1" else 404)
        schema = client.get("/api/v1/openapi.json")
        assert schema.status_code == 200
        assert "/api/v1/health" in schema.json()["paths"]
        assert not any("quota" in path for path in schema.json()["paths"])
        assert client.get("/api/v1/ai-quota").status_code == 404


def test_invalid_docs_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("API_DOCS_ENABLED", "invalid")
    with pytest.raises(ValueError, match="API_DOCS_ENABLED"):
        create_app()


def test_public_resources_have_no_credentials_or_private_files():
    public = ROOT / "backend/app/web/static"
    for file in public.rglob("*"):
        if file.is_file():
            assert file.suffix.lower() in {".css", ".js", ".svg"}
            body = file.read_text(encoding="utf-8")
            assert not re.search(r"(?:ghp_|github_pat_|hf_|sk-proj-)[A-Za-z0-9_-]{20,}", body)
            assert "PRIVATE KEY-----" not in body
            assert not re.search(r"(?:DATABASE_URL|POSTGRES_PASSWORD)\s*=", body)
    with TestClient(create_app()) as client:
        for path in ["/static/.env", "/static/private_media/test.wav", "/static/models/model.bin"]:
            assert client.get(path).status_code == 404


def test_image_api_response_is_never_cacheable_without_authentication():
    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/images/{uuid4()}")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
