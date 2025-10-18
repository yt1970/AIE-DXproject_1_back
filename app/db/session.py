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
import os

DEFAULT_SQLITE_URL = "sqlite:///./app_dev.sqlite3"

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ----------------------------------------------------------------------
# 1. 環境変数の読み込み
# ----------------------------------------------------------------------
# .envファイルから環境変数を読み込みます。
# これにより、DATABASE_URLのような機密情報をコードに直接記述するのを防ぎます。
load_dotenv()

# 環境変数からデータベース接続URLを取得します。
# .envファイルに `DATABASE_URL="postgresql://user:password@host:port/dbname"` のように記述します。
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = DEFAULT_SQLITE_URL
    logger.warning(
        "環境変数 'DATABASE_URL' が設定されていないため、SQLiteを使用します: %s",
        DATABASE_URL,
    )

# ----------------------------------------------------------------------
# 2. データベースエンジンの作成
# ----------------------------------------------------------------------
# SQLAlchemyの'エンジン'は、データベースとの主要な接続点です。
# create_engineは一度だけ呼び出され、アプリケーション全体で再利用されます。
# `pool_pre_ping=True` は、接続プールから接続を取得する際に、
# その接続がまだ有効か（例：DBサーバーから切断されていないか）をテストする設定です。
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

# ----------------------------------------------------------------------
# 3. セッションファクトリの作成
# ----------------------------------------------------------------------
# SessionLocalは、データベースセッションを作成するための'ファクトリ'（工場）です。
# `sessionmaker` は、このファクトリを構成します。
# - autocommit=False: トランザクションを手動でコミットするようにします。
# - autoflush=False: クエリ前に自動でflushしないようにします。
# - bind=engine: このセッションファクトリが上記のエンジンを使用することを示します。
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ----------------------------------------------------------------------
# 4. 依存性注入用のDBセッション提供関数
# ----------------------------------------------------------------------
# この関数 `get_db` は、FastAPIのエンドポイントで `Depends(get_db)` のように使われます。
# この関数が呼ばれるたびに、新しいデータベースセッションが作成され、
# APIリクエストの処理が完了した後に、セッションが確実にクローズされることを保証します。
# `yield` を使うことで、リクエスト処理中はセッションを貸し出し、処理が終わったら後続処理（finally）を実行します。
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
