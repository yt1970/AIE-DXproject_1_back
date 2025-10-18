"""Application package exposing the FastAPI app factory."""

from .main import app, create_app, settings

__all__ = ["app", "create_app", "settings"]
