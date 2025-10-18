"""FastAPI application entrypoint for the AIE-DXproject backend."""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI


@lru_cache
def settings() -> dict[str, str]:
    """Load configuration from environment variables."""
    return {
        "env": os.getenv("APP_ENV", "development"),
        "title": os.getenv("API_TITLE", "AIE-DXproject Backend"),
        "debug": os.getenv("API_DEBUG", "false").lower() == "true",
    }


def create_app() -> FastAPI:
    """Application factory for easier testing."""
    config = settings()
    app = FastAPI(title=config["title"], debug=config["debug"])

    @app.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        """Return service health information."""
        return {"status": "ok", "environment": config["env"]}

    return app


app = create_app()
