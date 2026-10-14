from collections.abc import Generator
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import settings
from backend.db.base import Base


logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_database() -> None:
    import backend.db.models  # noqa: F401
    from backend.services.accounts import AccountService
    from backend.services.categorization import CategorizationService
    from backend.services.plaid import PlaidService
    from backend.services.plaid_vault import PlaidVault

    with engine.begin() as connection:
        connection.execute(text("create schema if not exists raw"))
        connection.execute(text("create schema if not exists core"))
        connection.execute(text("create schema if not exists enrichment"))
        connection.execute(text("create schema if not exists planning"))
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        CategorizationService(session).seed_defaults()
        AccountService(session).link_legacy_statements()
        if settings.plaid_vault_key.strip():
            restored = PlaidVault().restore(session)
            for item_id in restored:
                try:
                    PlaidService(session).sync_transactions(item_id=item_id)
                except Exception:
                    session.rollback()
                    logger.warning("A recovered Plaid connection needs a manual sync or reauthentication.")


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
