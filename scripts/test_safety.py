"""Autorisation explicite des clusters jetables ; jamais importée en production."""

import hashlib
import json
import os
import re
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION = "P14_TEST_AUTHORIZATION"
DENIED_PORTS = {5432, 5433, 5434}
DATABASES = {"p07_validation", "p20_validation"}
OFFLINE = {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "PYTHON_DOTENV_DISABLED": "1",
}


class UnsafeTestTarget(ValueError):
    """Message fixe : ni URL, ni mot de passe, ni chemin dans les diagnostics."""


def refuse():
    raise UnsafeTestTarget("Cible de test absente, contradictoire ou non autorisée") from None


def checked_url(value):
    try:
        url = make_url(value)
        if (url.drivername != "postgresql+psycopg" or url.host != "127.0.0.1"
                or not url.port or url.port in DENIED_PORTS
                or not (url.database in DATABASES or re.fullmatch(r"p07_real_[a-f0-9]{12}",
                                                                url.database or ""))
                or not re.fullmatch(r"(?:p07_|p20_|real_)[a-f0-9]{12}", url.username or "")
                or not url.password):
            refuse()
        if url.query and not (set(url.query) == {"options"} and re.fullmatch(
                r"-csearch_path=p02_test_[a-f0-9]{32}", url.query["options"])):
            refuse()
        return url
    except Exception:
        refuse()


def fingerprint(url):
    raw = url.set(query={}).render_as_string(hide_password=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def checked_root(directory):
    path = Path(directory).resolve()
    if (path.is_relative_to(ROOT) or "onedrive" in str(path).lower()
            or not path.name.startswith(("p07_jobs_", "dreams_p20_", "p14_tests_", "p07-real-"))
            or Path(directory).is_symlink() or Path(directory).is_junction()):
        refuse()
    return path


def authorize(directory, url):
    """Seulement après initdb dans un nouveau répertoire du lanceur propriétaire."""
    url = checked_url(url)
    directory = checked_root(directory)
    if not (directory / "data/PG_VERSION").is_file():
        refuse()
    manifest = directory / "p14-test-target.json"
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump({"version": 1, "target": fingerprint(url)}, stream)
    return manifest


def validate_target(env, value=None):
    """Validation sans réseau ; les deux URL doivent désigner exactement la cible."""
    try:
        if any(key.upper().startswith("PG") for key in env):
            refuse()
        manifest = Path(env[AUTHORIZATION])
        directory = checked_root(manifest.parent)
        if (manifest.name != "p14-test-target.json" or manifest.is_symlink()
                or manifest.is_junction() or manifest.stat().st_size > 1024
                or not (directory / "data/PG_VERSION").is_file()):
            refuse()
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        database, test = checked_url(env["DATABASE_URL"]), checked_url(env["TEST_DATABASE_URL"])
        target = checked_url(value) if value is not None else test
        if (metadata.get("version") != 1 or fingerprint(database) != fingerprint(test)
                or fingerprint(target) != metadata.get("target")
                or fingerprint(test) != metadata.get("target")):
            refuse()
        return target
    except Exception:
        refuse()


def verify_server(connection, env):
    """Premières lectures avant migration : identité réelle du cluster autorisé."""
    target = validate_target(env)
    expected = Path(env[AUTHORIZATION]).parent / "data"
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, inet_server_port(), "
                       "current_setting('data_directory')")
        database, role, port, data = cursor.fetchone()
    if (database != target.database or role != target.username or port != target.port
            or Path(data).resolve() != expected.resolve()):
        refuse()


def probe(env):
    """Identité du serveur avant migration ou création des fixtures applicatives."""
    import psycopg

    target = validate_target(env)
    with psycopg.connect(host=target.host, port=target.port, dbname=target.database,
                         user=target.username, password=target.password,
                         connect_timeout=5) as connection:
        verify_server(connection, env)


def clean_environment(source=None):
    """Aucun .env personnel, ciblage PG hérité ou opt-in IA dans les tests ordinaires."""
    source = os.environ if source is None else source
    result = {key: value for key, value in source.items()
              if not key.upper().startswith(("PG", "RUN_", "P14_"))
              and key not in {"DATABASE_URL", "TEST_DATABASE_URL", "PRIVATE_MEDIA_ROOT",
                              "EXPORT_TEMP_ROOT", "WEB_TEST_URL", "IMAGE_RECEIPT_PATH",
                              "IMAGE_MODEL_PATH", "STT_MODEL_PATH", "EMOTION_MODEL_PATH",
                              "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
              and not any(part in key.upper() for part in ("TOKEN", "SECRET", "PASSWORD",
                                                           "API_KEY", "PROXY"))}
    result.update(OFFLINE)
    result.update(EMOTION_ENABLED="0", DATABASE_URL="", TEST_DATABASE_URL="")
    return result


def isolated_environment(directory, url, source=None):
    env = clean_environment(source)
    raw = url.render_as_string(hide_password=False)
    env.update(DATABASE_URL=raw, TEST_DATABASE_URL=raw,
               PRIVATE_MEDIA_ROOT=str(Path(directory) / "private_media"),
               EXPORT_TEMP_ROOT=str(Path(directory) / "exports"),
               P14_TEST_AUTHORIZATION=str(authorize(directory, url)))
    validate_target(env)
    return env
