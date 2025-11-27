# backend/main.py
"""FastAPI application entrypoint for the AIE-DXproject backend."""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# --- 分割したルーターと設定関連をインポート ---
from app.api import analysis, comments, courses, lectures, metrics, upload
from app.core.settings import get_settings
from app.db.migrations import apply_migrations
from app.db.session import engine

settings = get_settings()


# ----------------------------------------------------------------------
# アプリケーションファクトリ (テストの容易性のために関数化)
# ----------------------------------------------------------------------
def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    config = settings

    app = FastAPI(
        title=config.title,
        debug=config.debug,
        version="1.0.0",
    )

    # ------------------------------------------------------------------
    # 1. 起動時のイベントハンドラ (DB接続の初期化などを想定)
    # ------------------------------------------------------------------
    @app.on_event("startup")
    async def startup_event():
        # 実際にはここでDB接続やCeleryワーカーの初期設定を行う
        print(f"Application '{app.title}' starting up. ENV: {config.env}")
        # 例: await initialize_database_connection()
        apply_migrations(engine)

    # ------------------------------------------------------------------
    # 2. ヘルスチェックエンドポイント
    # ------------------------------------------------------------------
    @app.get("/health", tags=["System"])
    def health_check():
        """
        システムの稼働状況を確認するためのヘルスチェックエンドポイント。
        """
        return JSONResponse(
            content={
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                "app_name": app.title,
                "environment": config.env,
                # 実際にはDB接続やCeleryキューの状態チェックを追加
            }
        )

    # ------------------------------------------------------------------
    # 3. ルーターの登録
    # ------------------------------------------------------------------
    app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
    app.include_router(analysis.router, prefix="/api/v1", tags=["Analysis"])
    app.include_router(comments.router, prefix="/api/v1", tags=["Results"])
    app.include_router(courses.router, prefix="/api/v1", tags=["Courses"])
    app.include_router(lectures.router, prefix="/api/v1", tags=["Lectures"])
    app.include_router(metrics.router, prefix="/api/v1", tags=["Metrics"])
    from app.api import dashboard

    app.include_router(dashboard.router, prefix="/api/v1", tags=["Dashboard"])

    return app


# グローバルなアプリケーションインスタンスを作成
app = create_app()
