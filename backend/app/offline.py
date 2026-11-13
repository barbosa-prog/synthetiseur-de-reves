"""Environnement des processus d'inférence locaux, sans téléchargement implicite."""

import os

OFFLINE_FLAGS = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
}


def inference_environment():
    """Conserve les chemins/paramètres système ; retire les secrets non nécessaires.

    Ce n'est pas un pare-feu : les chargeurs doivent aussi rester local_files_only.
    Le dictionnaire retourné ne modifie jamais l'environnement du worker parent.
    """
    private = {"DATABASE_URL", "TEST_DATABASE_URL", "PGPASSWORD", "API_KEY", "TOKEN",
               "SECRET", "PASSWORD", "COOKIE", "AUTHORIZATION", "PGPASSFILE", "PGSERVICEFILE",
               "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in private and not key.upper().startswith("POSTGRES_")
           and not key.upper().endswith(
               ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_COOKIE"))}
    return {**env, **OFFLINE_FLAGS}
