"""Configuration explicite de PostgreSQL, sans connexion au chargement de l'API."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.safe_logging import install_safe_logging

ROOT = Path(__file__).resolve().parents[2]


class Base(DeclarativeBase):
    """Métadonnées partagées par les modèles SQLAlchemy."""


def database_url(variable: str = "DATABASE_URL") -> URL:
    """Lit une URL PostgreSQL sans l'afficher.

    Args:
        variable: Nom de la variable de configuration.

    Returns:
        URL SQLAlchemy validée.

    Raises:
        ValueError: Configuration absente ou non PostgreSQL.
    """
    load_dotenv(ROOT / ".env", override=False)
    value = os.getenv(variable)
    if not value:
        raise ValueError(f"Définir {variable} dans l'environnement ou le fichier .env privé.")
    try:
        url = make_url(value)
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError
        if url.password in {"REPLACE_WITH_LOCAL_RANDOM_PASSWORD", "REPLACE_ME"}:
            raise ValueError
        return url
    except Exception:
        raise ValueError(f"Configuration {variable} invalide ; URL et secrets masqués.") from None


def make_engine(url: URL | None = None) -> Engine:
    """Crée un moteur sans journalisation SQL ni paramètres.

    Args:
        url: URL explicite ou configuration DATABASE_URL.

    Returns:
        Moteur ; la première connexion est différée.
    """
    install_safe_logging()
    return create_engine(
        url if url is not None else database_url(),
        echo=False, hide_parameters=True, pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Prépare des sessions transactionnelles pour un moteur explicite.

    Args:
        engine: Moteur de connexion.

    Returns:
        Fabrique de sessions à utiliser avec un gestionnaire de contexte.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)
