"""Compatibilité Windows des seuls clusters PostgreSQL jetables P14."""

import csv
import os
import re
import subprocess
import tempfile
from pathlib import Path

from scripts.test_safety import checked_root, clean_environment


class PostgresTestFailure(RuntimeError):
    """Diagnostic borné, sans sortie native, SID, commande ou chemin."""


def prepare_directory(directory):
    """Accès du SID utilisateur conservé après réduction du jeton Administrateurs.

    Aucun Everyone/Users, pas de /T, /reset ou modification d'un parent existant.
    Appeler immédiatement après TemporaryDirectory, avant mot de passe et data.
    """
    directory = checked_root(directory)
    if any(directory.iterdir()):
        raise PostgresTestFailure("postgres_setup:directory_not_empty")
    if os.name != "nt":
        return
    try:
        identity = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            capture_output=True, timeout=15, env=clean_environment(),
        )
        rows = list(csv.reader(identity.stdout.decode("utf-8", errors="replace").splitlines()))
        if identity.returncode or len(rows) != 1 or len(rows[0]) != 2:
            raise ValueError
        sid = rows[0][1].strip()
        if not re.fullmatch(r"S-1-5-21-\d+-\d+-\d+-\d+", sid):
            raise ValueError
        grant = subprocess.run(
            ["icacls.exe", str(directory), "/grant", f"*{sid}:(OI)(CI)F", "/q"],
            capture_output=True, timeout=15, env=clean_environment(),
        )
        if grant.returncode:
            raise PostgresTestFailure("postgres_setup:user_acl_failed")
    except PostgresTestFailure:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise PostgresTestFailure("postgres_setup:user_acl_unavailable") from None
    print("PostgreSQL temporaire : accès utilisateur explicite préparé.", flush=True)


def failure_category(returncode, output):
    text = output.decode("utf-8", errors="replace").lower()
    if any(token in text for token in ("permission denied", "access is denied", "access denied",
                                       "accès refusé", "could not change permissions")):
        return "permission_denied"
    if "not empty" in text:
        return "directory_not_empty"
    if "locale" in text and ("invalid" in text or "not supported" in text):
        return "invalid_locale"
    if "password authentication failed" in text:
        return "authentication_failed"
    if returncode & 0xFFFFFFFF in {0xC0000135, 0xC000007B}:
        return "runtime_unavailable"
    return "process_failed"


def postgres_command(args, env=None):
    stage = {"initdb.exe": "initdb", "pg_ctl.exe": "pg_ctl",
             "createdb.exe": "createdb"}.get(Path(args[0]).name.lower(), "tool")
    try:
        # pg_ctl peut laisser ses handles à postgres : un PIPE attendrait sa fin,
        # même après le retour réussi de pg_ctl. Un fichier privé évite cette attente.
        with tempfile.TemporaryFile() as diagnostics:
            result = subprocess.run(args, env=env if env is not None else clean_environment(),
                                    stdout=diagnostics, stderr=subprocess.STDOUT, timeout=90)
            diagnostics.seek(0)
            output = diagnostics.read(65536)
    except subprocess.TimeoutExpired:
        raise PostgresTestFailure(f"postgres_temporary:{stage}:timeout") from None
    except PermissionError:
        raise PostgresTestFailure(f"postgres_temporary:{stage}:executable_denied") from None
    except FileNotFoundError:
        raise PostgresTestFailure(f"postgres_temporary:{stage}:executable_missing") from None
    except OSError:
        raise PostgresTestFailure(f"postgres_temporary:{stage}:executable_failed") from None
    if result.returncode:
        category = failure_category(result.returncode, output)
        raise PostgresTestFailure(
            f"postgres_temporary:{stage}:{category}:exit={result.returncode}"
        ) from None
