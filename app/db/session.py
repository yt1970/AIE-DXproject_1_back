# app/db/session.py

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings

DEFAULT_SQLITE_URL = "sqlite:///./app_dev.sqlite3"

logger = logging.getLogger(__name__)

settings = get_settings()
DATABASE_URL = settings.database_url or DEFAULT_SQLITE_URL

if DATABASE_URL == DEFAULT_SQLITE_URL:
    logger.warning(
        "環境変数 'DATABASE_URL' が設定されていないため、SQLiteを使用します: %s",
        DATABASE_URL,
    )

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    FastAPI依存性注入用のDBセッションをリクエスト単位で提供する。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
