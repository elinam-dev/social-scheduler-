from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    settings = Settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


SessionLocal = get_session_factory()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
