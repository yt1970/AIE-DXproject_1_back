# backend/main.py
"""FastAPI application entrypoint for the AIE-DXproject backend."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# --- 分割したルーターをインポート ---
from app.api import analysis, comments, upload


# ----------------------------------------------------------------------
# 設定の読み込み (lru_cacheで一度だけ読み込む)
# ----------------------------------------------------------------------
# 環境変数を管理するPydantic Settingsモデルを想定したダミー
@lru_cache
def get_app_settings() -> dict[str, str | bool]:
    """Load application configuration from environment variables."""
    # .env ファイルからロードされる値を想定
    return {
        "env": os.getenv("APP_ENV", "development"),
        "title": os.getenv("API_TITLE", "AIE-DXproject Backend"),
        "debug": os.getenv("API_DEBUG", "False").lower() == "true",
    }


settings = get_app_settings()


# ----------------------------------------------------------------------
# アプリケーションファクトリ (テストの容易性のために関数化)
# ----------------------------------------------------------------------
def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    config = settings
    
    app = FastAPI(
        title=config["title"], 
        debug=config["debug"],
        version="1.0.0",
    )
    
    # ------------------------------------------------------------------
    # 1. 起動時のイベントハンドラ (DB接続の初期化などを想定)
    # ------------------------------------------------------------------
    @app.on_event("startup")
    async def startup_event():
        # 実際にはここでDB接続やCeleryワーカーの初期設定を行う
        print(f"Application '{app.title}' starting up. ENV: {config['env']}")
        # 例: await initialize_database_connection()


    # ------------------------------------------------------------------
    # 2. ヘルスチェックエンドポイント
    # ------------------------------------------------------------------
    @app.get("/health", tags=["System"])
    def health_check():
        """
        システムの稼働状況を確認するためのヘルスチェックエンドポイント。
        """
        return JSONResponse(content={
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "app_name": app.title,
            "environment": config["env"],
            # 実際にはDB接続やCeleryキューの状態チェックを追加
        })


    # ------------------------------------------------------------------
    # 3. ルーターの登録
    # ------------------------------------------------------------------
    app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
    app.include_router(analysis.router, prefix="/api/v1", tags=["Analysis"])
    app.include_router(comments.router, prefix="/api/v1", tags=["Results"])

    return app


# グローバルなアプリケーションインスタンスを作成
app = create_app()
