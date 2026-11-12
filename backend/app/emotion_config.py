"""Configuration publique reproductible ; aucun moteur ou accès DB à l'import."""

import os
from pathlib import Path

REVISION = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
TIMEOUT = 120


def local_root():
    return Path(os.environ["LOCALAPPDATA"]) / "SynthetiseurDeReves/qualification"


def enabled():
    return os.getenv("EMOTION_ENABLED", "0") == "1"


def parameters():
    """Politique 2C prudente, expérimentale ; pas la référence plus permissive."""
    return dict(
        engine="mdeberta-experimental",
        model_revision=REVISION,
        tokenizer_revision=REVISION,
        strategy_revision="p08-2c-prudent-v1",
        policy="suggestion-only-v2",
        inference_enabled=enabled(),
        variant=1,
        threshold=0.45,
        margin=0.05,
        gate_threshold=0.4,
        lexical_guard=False,
        chunk_tokens=300,
        max_tokens=512,
        min_tokens=5,
        max_characters=20000,
        threads=2,
        interop_threads=1,
        seed=42,
        dtype="float32",
        device="cpu",
        timeout_seconds=TIMEOUT,
        min_free_mib=1536,
        initial_free_mib=3584,
        private_limit_mib=3072,
        policy_sha256="b3204c03f616a5a7806cf35346806e7e0ca9521eaa74d1b8848cafe3225a9003",
        dependencies={
            "torch": "2.7.1+cpu",
            "transformers": "4.57.3",
            "tokenizers": "0.22.2",
            "safetensors": "0.7.0",
            "psutil": "7.1.3",
        },
        python="3.12.14",
    )
