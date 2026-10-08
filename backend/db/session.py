from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.core.config import settings
from backend.db.base import Base

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_database() -> None:
    import backend.db.models  # noqa: F401
    from backend.services.categorization import CategorizationService

    with engine.begin() as connection:
        connection.execute(text("create schema if not exists raw"))
        connection.execute(text("create schema if not exists enrichment"))
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        CategorizationService(session).seed_defaults()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
