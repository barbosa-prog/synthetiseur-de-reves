"""Recette isolée Windows : PostgreSQL natif temporaire, HTTPS, pytest et Chrome/Edge."""

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import trustme
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    """Réserve un numéro libre pour les services de test locaux."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    """Ne touche à aucune base ou service existant et n'affiche aucun secret."""
    pg = Path(os.getenv("P20_POSTGRES_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    if not (pg / "initdb.exe").is_file():
        raise SystemExit("PostgreSQL natif absent : configurer P20_POSTGRES_BIN.")
    with tempfile.TemporaryDirectory(prefix="dreams_p20_") as temporary:
        directory = Path(temporary)
        data = directory / "data"
        password = secrets.token_hex(24)
        role = "p20_" + secrets.token_hex(6)
        password_file = directory / "password"
        password_file.write_text(password, encoding="utf-8")

        def run_pg(args, env=None):
            result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=90)
            if result.returncode:
                raise RuntimeError("Opération PostgreSQL temporaire échouée ; détails masqués.")

        run_pg([str(pg / "initdb.exe"), "-D", str(data), "-U", role,
                "--pwfile", str(password_file), "-A", "scram-sha-256",
                "--encoding=UTF8", "--locale=C"])
        password_file.unlink()
        db_port, web_port = free_port(), free_port()
        started, server = False, None
        try:
            run_pg([str(pg / "pg_ctl.exe"), "-D", str(data), "-l", str(directory / "pg.log"),
                    "-o", f"-h 127.0.0.1 -p {db_port}", "-w", "start"])
            started = True
            print("PostgreSQL temporaire démarré.", flush=True)
            env = os.environ.copy()
            env["PGPASSWORD"] = password
            run_pg([str(pg / "createdb.exe"), "-h", "127.0.0.1", "-p", str(db_port),
                    "-U", role, "p20_validation"], env)
            url = URL.create("postgresql+psycopg", username=role, password=password,
                             host="127.0.0.1", port=db_port, database="p20_validation")
            raw_url = url.render_as_string(hide_password=False)
            origin = f"https://127.0.0.1:{web_port}"
            env.update(DATABASE_URL=raw_url, TEST_DATABASE_URL=raw_url,
                       WEB_ORIGIN=origin, WEB_TEST_URL=origin)
            result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                    cwd=ROOT, env=env, capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError("Migration de test échouée ; détails privés masqués.")
            authority = trustme.CA()
            certificate = authority.issue_cert("localhost", "127.0.0.1")
            certificate.private_key_pem.write_to_path(directory / "key.pem")
            certificate.cert_chain_pems[0].write_to_path(directory / "cert.pem")
            server = subprocess.Popen([
                sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
                "--port", str(web_port), "--no-access-log", "--no-proxy-headers",
                "--ssl-keyfile", str(directory / "key.pem"),
                "--ssl-certfile", str(directory / "cert.pem"),
            ], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with httpx.Client(verify=False, trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get(origin + "/api/v1/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Serveur HTTPS temporaire indisponible.")
            result = subprocess.run([
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                "--cov=backend.app", "--cov-report=term-missing", "--cov-fail-under=80",
            ], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
            output = result.stdout + result.stderr
            for secret in (raw_url, password, role):
                output = output.replace(secret, "[MASQUÉ]")
            print(output, flush=True)
            return result.returncode
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=15)
            if started:
                run_pg([str(pg / "pg_ctl.exe"), "-D", str(data), "-m", "fast", "-w", "stop"])
            print("Serveurs temporaires arrêtés.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
