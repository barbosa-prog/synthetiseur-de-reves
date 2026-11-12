"""Sous-processus CPU hors ligne ; récit par stdin uniquement, jamais en argv."""

import faulthandler
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from pathlib import Path

os.environ.update(
    CUDA_VISIBLE_DEVICES="",
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    TOKENIZERS_PARALLELISM="false",
    OMP_NUM_THREADS="2",
    MKL_NUM_THREADS="2",
)


def main():
    payload = json.loads(sys.stdin.buffer.readline(131073))
    config, request = payload["configuration"], payload["request"]
    if not config["inference_enabled"]:
        return dict(error="disabled")
    if platform.python_version() != config["python"] or any(
        importlib.metadata.version(name) != version
        for name, version in config["dependencies"].items()
    ):
        return dict(error="configuration")
    root = Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/qualification/p08b/model"
    if not root.is_dir():
        return dict(error="model_unavailable")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest["repo"] != "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
        or manifest["revision"] != config["model_revision"]
        or manifest["license"] != "mit"
    ):
        return dict(error="configuration")
    # Les deux gros fichiers sont liés aux empreintes officielles déjà qualifiées.
    fixed = {
        "model.safetensors": "65af59b1ff4450b09ecbf13ca35c840dbf038b26ff8e10e5ea89ca724828ed1e",
        "tokenizer.json": "3aca3ce69a0a35aeb144a52c4f1d41c4246b8785f8f398315cc8fb6b24057810",
    }
    required = {
        "README.md",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "model.safetensors",
    }
    if set(manifest["files"]) != required:
        return dict(error="model_unavailable")
    for name, entry in manifest["files"].items():
        if name not in {
            "README.md",
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "added_tokens.json",
            "model.safetensors",
        }:
            return dict(error="configuration")
        file = root / name
        if file.is_symlink() or file.resolve().parent != root.resolve():
            return dict(error="configuration")
        if not file.is_file() or file.stat().st_size != entry["bytes"]:
            return dict(error="model_unavailable")
        with file.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != fixed.get(name, entry["sha256"]):
            return dict(error="model_unavailable")
    qualification = Path(__file__).resolve().parents[1] / "qualification/p08"
    if (
        hashlib.sha256((qualification / "reliability.py").read_bytes()).hexdigest()
        != config["policy_sha256"]
    ):
        return dict(error="configuration")
    sys.path.insert(0, str(qualification))
    import torch
    from reliability import decide, features
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if torch.version.cuda is not None:
        return dict(error="configuration")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        root, local_files_only=True, trust_remote_code=False, use_fast=True
    )
    model = (
        AutoModelForSequenceClassification.from_pretrained(
            root,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=torch.float32,
        )
        .to("cpu")
        .eval()
    )
    if not all(p.device.type == "cpu" and p.dtype == torch.float32 for p in model.parameters()):
        return dict(error="configuration")
    loading = time.perf_counter() - started
    started = time.perf_counter()
    raw = features(model, tokenizer, torch, request["text"], config["variant"])
    emotion, reason = decide(raw, config)
    mapped = (
        "insufficient_information"
        if reason
        in {"invalid_text", "insufficient_information", "undetermined", "no_explicit_evidence"}
        else "ambiguous"
    )
    return dict(
        result=dict(
            request_id=request["request_id"],
            text_version=request["text_version"],
            choice_revision=request["choice_revision"],
            emotion=emotion,
            abstention_reason=None if emotion else mapped,
            engine=config["engine"],
            model_revision=config["model_revision"],
        ),
        timings=dict(
            load_seconds=loading,
            inference_seconds=time.perf_counter() - started,
            child_cpu_seconds=time.process_time(),
        ),
    )


if __name__ == "__main__":
    faulthandler.enable()
    try:
        response = main()
    except Exception:
        response = dict(error="provider_failed")
    print(json.dumps(response), flush=True)
