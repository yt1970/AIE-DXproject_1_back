# backend/main.py
"""FastAPI application entrypoint for the AIE-DXproject backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        print(f"Application '{app.title}' starting up. ENV: {config.env}")
        # apply_migrations(engine)
        yield
        # Shutdown hook placeholder

    app = FastAPI(
        title=config.title,
        debug=config.debug,
        version="1.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Exception Handlers
    # ------------------------------------------------------------------
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        error_code = "INTERNAL_ERROR"
        if exc.status_code == 400:
            error_code = "INVALID_REQUEST"
        elif exc.status_code == 401:
            error_code = "UNAUTHORIZED"
        elif exc.status_code == 403:
            error_code = "FORBIDDEN"
        elif exc.status_code == 404:
            error_code = "NOT_FOUND"
        elif exc.status_code == 409:
            error_code = "CONFLICT"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": error_code, "message": exc.detail, "details": {}}
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Validation Error",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        import traceback

        print(f"Unhandled exception: {exc}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Internal Server Error",
                    "details": {"reason": str(exc)} if config.debug else {},
                }
            },
        )

    # ------------------------------------------------------------------
    # 1. Middleware
    # ------------------------------------------------------------------
    from app.core.middleware import AuthMiddleware

    app.add_middleware(AuthMiddleware, debug=config.debug)

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

    from app.api import auth, common

    app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
    app.include_router(common.router, prefix="/api/v1", tags=["Common"])

    from app.api import trends

    app.include_router(trends.router, prefix="/api/v1", tags=["Trends"])

    from app.api import dashboard

    app.include_router(dashboard.router, prefix="/api/v1", tags=["Dashboard"])

    return app


# グローバルなアプリケーションインスタンスを作成
app = create_app()
