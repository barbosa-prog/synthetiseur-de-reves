"""P15 : démonstration HTTPS jetable, sans configuration ni données personnelles."""

import argparse
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import trustme
from sqlalchemy import URL, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.database import make_engine  # noqa: E402
from backend.app.web.security import SESSION_COOKIE  # noqa: E402
from scripts.postgres_test_runtime import postgres_command, prepare_directory  # noqa: E402
from scripts.test_safety import clean_environment, isolated_environment, probe  # noqa: E402


class DemoFailure(Exception):
    """Code interne constant ; aucune exception tierce ni donnée privée."""


def require(condition, code):
    if not condition:
        raise DemoFailure(code)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_private(command, env, code):
    """Aucune sortie de migration/serveur susceptible de contenir une URL privée."""
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=60)
    require(result.returncode == 0, code)


def stop_services(server, started, pg, data, web_port):
    """Arrête exclusivement les processus créés par cet appel du lanceur."""
    try:
        if server is not None and server.poll() is None:
            server.terminate()
            server.wait(timeout=15)
    finally:
        # Même si l'arrêt du serveur échoue, arrêter notre cluster PostgreSQL.
        if started:
            postgres_command([str(pg / "pg_ctl.exe"), "-D", str(data),
                              "-m", "fast", "-w", "stop"])
            status = subprocess.run([str(pg / "pg_ctl.exe"), "-D", str(data), "status"],
                                    capture_output=True, env=clean_environment(), timeout=15)
            require(status.returncode == 3, "postgresql_pas_arrete")
    if server is not None:
        with socket.socket() as sock:
            sock.settimeout(1)
            require(sock.connect_ex(("127.0.0.1", web_port)) != 0, "port_web_encore_actif")
    print("Services jetables arrêtés.", flush=True)


def verify_application(client, origin, url):
    """Traverse HTTPS -> FastAPI -> PostgreSQL, puis la session web Jinja2."""
    require(client.get("/api/v1/health").json()["status"] == "ok", "sante_api")
    require(client.get("/api/v1/openapi.json").status_code == 200, "openapi")
    require(client.get("/api/v1/docs").status_code == 404, "docs_desactivees")
    require(client.get("/static/css/app.css").status_code == 200, "css_livre")
    email = "p15-fiction@example.com"
    password = secrets.token_urlsafe(32)
    credentials = {"email": email, "password": password}
    require(client.post("/api/v1/auth/register", json=credentials).status_code == 201,
            "inscription_api")
    login = client.post("/api/v1/auth/login", json=credentials)
    require(login.status_code == 200, "connexion_api")
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    history = client.get("/api/v1/dreams", headers=headers)
    require(history.status_code == 200 and history.json()["total"] == 0, "lecture_postgresql")
    page = client.get("/connexion")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)
    require(page.status_code == 200 and csrf is not None, "formulaire_jinja")
    login = client.post("/connexion", data={**credentials, "csrf": csrf[1]},
                        headers={"Origin": origin, "Referer": origin + "/connexion"})
    require(login.status_code == 303, "connexion_web")
    require(client.get("/mes-reves").status_code == 200, "session_web")
    cookies = [cookie for cookie in client.cookies.jar if cookie.name == SESSION_COOKIE]
    require(len(cookies) == 1 and cookies[0].secure and cookies[0].has_nonstandard_attr("HttpOnly"),
            "cookie_securise")
    engine = make_engine(url)
    try:
        with engine.connect() as db:
            require(db.scalar(text("SELECT count(*) FROM users WHERE email = :email"),
                              {"email": email}) == 1, "persistance_postgresql")
    finally:
        engine.dispose()
    require(client.post("/api/v1/auth/logout", headers=headers).status_code == 204,
            "deconnexion_api")
    require(client.get("/api/v1/auth/session", headers=headers).status_code == 401,
            "session_revoquee")
    print("Recette : santé, migrations, CSS, API/PostgreSQL, Jinja2 et sessions vérifiés.",
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Recette automatique puis arrêt ; sinon Ctrl+C pour arrêter")
    parser.add_argument("--stop-after", type=int, default=0,
                        help="Arrêt automatique de la démonstration après 1 à 3600 secondes")
    args = parser.parse_args()
    if args.stop_after and (args.check or not 1 <= args.stop_after <= 3600):
        parser.error("--stop-after exige 1 à 3600 secondes, sans --check")
    require(os.name == "nt" and sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32,
            "windows_python_312_64_bits_requis")
    pg = Path(os.getenv("P20_POSTGRES_BIN", r"C:\Program Files\PostgreSQL\17\bin"))
    require(all((pg / tool).is_file() for tool in (
        "initdb.exe", "pg_ctl.exe", "postgres.exe", "createdb.exe")), "postgresql_17_absent")
    version = subprocess.run([str(pg / "initdb.exe"), "--version"], capture_output=True,
                             env=clean_environment(), timeout=15)
    require(version.returncode == 0 and re.search(rb"\b17\.", version.stdout),
            "postgresql_17_requis")
    with tempfile.TemporaryDirectory(prefix="p14_tests_p15_") as temporary:
        directory = Path(temporary)
        prepare_directory(directory)
        data = directory / "data"
        password, role = secrets.token_hex(24), "p20_" + secrets.token_hex(6)
        password_file = directory / "password"
        password_file.write_text(password, encoding="utf-8")
        postgres_command([str(pg / "initdb.exe"), "-D", str(data), "-U", role,
                          "--pwfile", str(password_file), "-A", "scram-sha-256",
                          "--encoding=UTF8", "--locale=C"])
        password_file.unlink()
        db_port, web_port = free_port(), free_port()
        while db_port == web_port or db_port in {5432, 5433, 5434} or web_port == 8443:
            db_port, web_port = free_port(), free_port()
        server, started = None, False
        try:
            postgres_command([str(pg / "pg_ctl.exe"), "-D", str(data),
                              "-l", str(directory / "postgres.log"), "-o",
                              f"-h 127.0.0.1 -p {db_port}", "-w", "start"])
            started = True
            admin_env = clean_environment()
            admin_env["PGPASSWORD"] = password
            postgres_command([str(pg / "createdb.exe"), "-h", "127.0.0.1", "-p", str(db_port),
                              "-U", role, "p20_validation"], admin_env)
            url = URL.create("postgresql+psycopg", username=role, password=password,
                             host="127.0.0.1", port=db_port, database="p20_validation")
            env = isolated_environment(directory, url)
            probe(env)
            origin = f"https://127.0.0.1:{web_port}"
            env.update(WEB_ORIGIN=origin, API_DOCS_ENABLED="0", EMOTION_ENABLED="0")
            for action in ("upgrade", "current", "check"):
                command = [sys.executable, "-m", "alembic", action]
                run_private(command + (["head"] if action == "upgrade" else []), env,
                            "alembic_" + action)
            authority = trustme.CA()
            certificate = authority.issue_cert("127.0.0.1", "localhost")
            certificate.private_key_pem.write_to_path(directory / "key.pem")
            certificate.cert_chain_pems[0].write_to_path(directory / "cert.pem")
            authority.cert_pem.write_to_path(directory / "ca.pem")
            server = subprocess.Popen([
                sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
                "--port", str(web_port), "--no-access-log", "--no-proxy-headers",
                "--ssl-keyfile", str(directory / "key.pem"),
                "--ssl-certfile", str(directory / "cert.pem"),
            ], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            tls = ssl.create_default_context(cafile=str(directory / "ca.pem"))
            with httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=10) as client:
                last_health_error = "aucune_reponse"
                for _ in range(100):
                    require(server.poll() is None, "serveur_arrete_pendant_demarrage")
                    if not args.check:
                        # Le navigateur décidera de la confiance TLS. Aucune requête
                        # privée n'est envoyée avant cette décision de l'utilisateur.
                        with socket.socket() as sock:
                            sock.settimeout(0.2)
                            if sock.connect_ex(("127.0.0.1", web_port)) == 0:
                                break
                        time.sleep(0.1)
                        continue
                    try:
                        health = client.get("/api/v1/health")
                        if health.status_code == 200:
                            break
                        last_health_error = "http_" + str(health.status_code)
                    except httpx.HTTPError as error:
                        last_health_error = ("certificat_tls" if "CERTIFICATE_VERIFY_FAILED" in
                                             str(error) else type(error).__name__)
                    time.sleep(0.1)
                else:
                    raise DemoFailure("delai_demarrage_depasse_" + last_health_error)
                if args.check:
                    verify_application(client, origin, url)
                else:
                    print(f"Démonstration JETABLE : {origin}/connexion", flush=True)
                    print("Certificat local non approuvé ; aucune autorité installée. "
                          "Données effacées à l'arrêt. Aucun worker IA. Ctrl+C pour arrêter.",
                          flush=True)
                    deadline = time.monotonic() + args.stop_after if args.stop_after else None
                    while server.poll() is None:
                        if deadline is not None and time.monotonic() >= deadline:
                            break
                        time.sleep(0.5)
                    require(server.poll() is None, "serveur_arrete")
        except KeyboardInterrupt:
            print("Arrêt de la démonstration.", flush=True)
        finally:
            stop_services(server, started, pg, data, web_port)
    require(not directory.exists(), "repertoire_temporaire_pas_supprime")
    print("Ressources jetables supprimées.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DemoFailure as error:
        print("Recette P15 échouée : " + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # Pas de traceback contenant configuration, cookies ou URL PostgreSQL.
        print("Recette P15 échouée ; vérifier prérequis et disponibilité des ports. "
              "Détails privés masqués.", file=sys.stderr)
        raise SystemExit(1) from None
