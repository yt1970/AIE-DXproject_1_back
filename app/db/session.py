# app/db/session.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、アプリケーション全体で利用するデータベース接続とセッションを管理します。
# FastAPIの依存性注入（Dependency Injection）システムと連携し、
# 各APIリクエストが独立したデータベースセッションを持てるように設計されています。
# これにより、スレッドセーフなデータベース操作が可能になります。
# ----------------------------------------------------------------------

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings

DEFAULT_SQLITE_URL = "sqlite:///./app_dev.sqlite3"

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 1. 設定の読み込み
# ----------------------------------------------------------------------
settings = get_settings()
DATABASE_URL = settings.database_url or DEFAULT_SQLITE_URL

if DATABASE_URL == DEFAULT_SQLITE_URL:
    logger.warning(
        "環境変数 'DATABASE_URL' が設定されていないため、SQLiteを使用します: %s",
        DATABASE_URL,
    )

# ----------------------------------------------------------------------
# 2. データベースエンジンの作成
# ----------------------------------------------------------------------
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

# ----------------------------------------------------------------------
# 3. セッションファクトリの作成
# ----------------------------------------------------------------------
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ----------------------------------------------------------------------
# 4. 依存性注入用のDBセッション提供関数
# ----------------------------------------------------------------------
def get_db():
    """
    FastAPIの依存性注入（DI）用のデータベースセッションジェネレータ。
    リクエストの開始時にセッションを提供し、終了時にクローズします。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
