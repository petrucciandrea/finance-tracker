"""
Database engine and session factory.

`SessionLocal` is what `app.deps.get_db` uses to yield a request-scoped
session. Kept separate from `app.models` so models don't import the engine
(avoids import-order issues and keeps models testable without a live DB).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(
    str(settings.database_url),
    pool_pre_ping=True,  # avoids errors from stale connections after DB restarts/idle timeouts
    echo=settings.debug,  # logs SQL statements when DEBUG=true, silent otherwise
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # lets you still read attributes on ORM objects after commit
)
