# app/db/init_db.py

import logging

from app.db.models import Base

from app.db.session import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db() -> None:
    """
    Base配下のテーブルを存在しなければ作成する。
    """
    logger.info("データベースのテーブルを作成しています... (存在しないテーブルのみ)")

    Base.metadata.create_all(bind=engine)

    logger.info("テーブルの作成が完了しました。")


if __name__ == "__main__":
    init_db()
