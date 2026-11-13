"""Identités serveur sans import IA, secret, chemin ou ressource volatile."""

import json

from backend.app.job_rules import EngineIdentity, digest


def identity(parameters):
    return EngineIdentity(engine=parameters["engine"],
        model_revision=parameters.get("model_revision", "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"),
        policy_revision="p11-v1",
        settings_digest=digest(json.dumps(parameters, sort_keys=True, separators=(",", ":"))))


def stt_parameters(config=None):
    from backend.app.stt_provider import STTConfig
    config = config or STTConfig.from_environment()
    # Le manifeste local, s'il existe, fournit la révision sans charger de poids.
    revision = "local-unverified"
    manifest = config.model_path / "download-complete.json"
    if manifest.is_file():
        try:
            revision = json.loads(manifest.read_text(encoding="utf-8"))["revision"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return dict(engine=config.engine, model_revision=revision, model="whisper-small",
                language="fr", compute_type="int8", device="cpu", beam_size=5,
                vad_filter=False, condition_on_previous_text=False, cpu_threads=4,
                policy="p05-local-v1")


def image_parameters(seed=42):
    return dict(engine="sd15-local", width=512, height=512, steps=20, seed=seed,
                dtype="float16", device="cuda", safety_checker=True)
