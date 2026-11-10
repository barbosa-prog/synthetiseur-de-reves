"""Migrations PostgreSQL ; aucune URL privée dans alembic.ini."""

from alembic import context

from backend.app import models  # noqa: F401
from backend.app.database import Base, database_url, make_engine

target_metadata = Base.metadata


def run_migrations() -> None:
    """Exécute le mode SQL hors ligne ou la migration transactionnelle."""
    if context.is_offline_mode():
        context.configure(
            dialect_name="postgresql", target_metadata=target_metadata, literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = make_engine(database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    except Exception:
        raise RuntimeError(
            "Migration échouée ; vérifier PostgreSQL et la configuration privée. Détails masqués."
        ) from None
    finally:
        engine.dispose()


run_migrations()
