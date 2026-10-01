
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm import declarative_base
from starlette.concurrency import run_in_threadpool

from ..config import get, get_int


engine = create_engine(
    get("DATABASE_URL"),
    pool_size=get_int("DB_POOL_SIZE"),
    max_overflow=get_int("DB_MAX_OVERFLOW"),
    pool_timeout=get_int("DB_POOL_TIMEOUT"),
    # Hands back a connection the server has already dropped - a failover, an
    # idle reaper, a proxy - instead of letting the first query on it fail.
    pool_pre_ping=True,
    pool_recycle=get_int("DB_POOL_RECYCLE"),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


async def get_db() -> AsyncGenerator[Session, None]:
    """Provide a request-scoped session without blocking the event loop."""
    db = SessionLocal()
    try:
        yield db
    finally:
        await run_in_threadpool(db.close)