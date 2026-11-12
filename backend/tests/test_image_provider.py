"""P07 phase 1 : moteurs synthétiques uniquement, aucun modèle ou GPU."""

import io
import subprocess
import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from backend.app.image_provider import (
    ImageError,
    ImageRequest,
    ImageResult,
    LocalStableDiffusion15,
    SD15Config,
    validate_result,
)
from backend.app.image_worker import ImageTask, prepare_image


@pytest.fixture
def request_image():
    return ImageRequest(description=" Forêt fictive sous une lune violette ",
                        text_version=3, description_version=1)


@pytest.fixture
def png():
    stream = io.BytesIO()
    Image.new("RGB", (512, 512), "purple").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def config(tmp_path):
    # Fichiers sentinelles, aucun poids réel et aucune désérialisation.
    for name in ("unet/diffusion_pytorch_model.fp16.safetensors",
                 "vae/diffusion_pytorch_model.fp16.safetensors",
                 "text_encoder/model.fp16.safetensors", "safety_checker/model.fp16.safetensors",
                 "model_index.json", "feature_extractor/preprocessor_config.json"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"synthetic-not-a-model")
    return SD15Config(tmp_path)


class FakeRunner:
    def __init__(self, png, blocked=False, error=None):
        self.png, self.blocked, self.error = png, blocked, error
        self.calls = []

    def run(self, config, request):
        self.calls.append((config, request))
        if self.error:
            raise self.error
        return self.png, self.blocked


@pytest.mark.parametrize("text", ["", "   ", "x"*501, "bad\x00text"])
def test_invalid_description(text):
    with pytest.raises(ValidationError):
        ImageRequest(description=text, text_version=1, description_version=1)


def test_snapshot_is_immutable_and_private(request_image):
    assert request_image.description.startswith("Forêt")
    assert "Forêt" not in repr(request_image)
    with pytest.raises(ValidationError):
        request_image.text_version = 4
    with pytest.raises(ValidationError):
        ImageRequest(description="test", text_version=0, description_version=1)


def test_adapter_uses_exact_description_no_translation(config, png, request_image):
    runner = FakeRunner(png)
    result = LocalStableDiffusion15(config, runner).generate(request_image)
    assert result.png == png and result.text_version == 3
    assert runner.calls == [(config, request_image)]
    assert config.steps == 20 and config.width == config.height == 512


def test_unwired_adapter_fails_closed(config, request_image):
    with pytest.raises(ImageError, match="worker_unavailable"):
        LocalStableDiffusion15(config).generate(request_image)


def test_missing_safety_weights_no_runner_call(config, png, request_image):
    (config.model_path / "safety_checker/model.fp16.safetensors").unlink()
    runner = FakeRunner(png)
    with pytest.raises(ImageError, match="model_unavailable"):
        LocalStableDiffusion15(config, runner).generate(request_image)
    assert runner.calls == []


@pytest.mark.parametrize("blocked,code", [(True, "safety_blocked"), (None, "provider_failed")])
def test_filter_is_mandatory(config, png, request_image, blocked, code):
    with pytest.raises(ImageError, match=code):
        LocalStableDiffusion15(config, FakeRunner(png, blocked)).generate(request_image)


@pytest.mark.parametrize("error,code", [(TimeoutError("private"), "timeout"),
                                       (RuntimeError("private/path dream"), "provider_failed")])
def test_errors_are_redacted_no_retry(config, png, request_image, error, code):
    runner = FakeRunner(png, error=error)
    with pytest.raises(ImageError) as exc:
        LocalStableDiffusion15(config, runner).generate(request_image)
    assert str(exc.value) == code and len(runner.calls) == 1


@pytest.mark.parametrize("content", [b"", b"not png", b"x"*(8*1024**2+1)])
def test_invalid_output(content, request_image):
    with pytest.raises(ImageError, match="invalid_image"):
        validate_result(ImageResult(content, 3, 1), request_image)


def test_wrong_dimensions(request_image):
    output = io.BytesIO()
    Image.new("RGB", (16, 16)).save(output, format="PNG")
    with pytest.raises(ImageError, match="invalid_image"):
        validate_result(ImageResult(output.getvalue(), 3, 1), request_image)


@pytest.mark.parametrize("text_version,description_version", [(2, 1), (3, 2)])
def test_wrong_result_version(png, request_image, text_version, description_version):
    with pytest.raises(ImageError, match="text_conflict"):
        validate_result(ImageResult(png, text_version, description_version), request_image)


@pytest.mark.parametrize("checks", [(False,), (True, False), (True, True)])
def test_worker_version_guards(config, png, request_image, checks):
    task = ImageTask(uuid4(), uuid4(), uuid4(), request_image)
    current = iter(checks)
    runner = FakeRunner(png)
    adapter = LocalStableDiffusion15(config, runner)
    if not all(checks):
        with pytest.raises(ImageError, match="text_conflict"):
            prepare_image(task, adapter, lambda _: next(current))
    else:
        assert prepare_image(task, adapter, lambda _: next(current)).png == png
    assert len(runner.calls) == int(checks[0])


def test_config_rejects_unqualified_parameters(config):
    with pytest.raises(ImageError, match="configuration"):
        replace(config, steps=2)


def test_imports_do_not_load_ai_or_database():
    code = """
import sys
import backend.app.image_provider
import backend.app.image_worker
assert not set(('torch', 'diffusers', 'transformers', 'backend.app.stt_provider',
                'backend.app.database')).intersection(sys.modules)
"""
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=15)
    assert completed.returncode == 0
