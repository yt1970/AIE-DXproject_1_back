"""Application package exposing the FastAPI app factory."""

from typing import TYPE_CHECKING

__all__ = ["app", "create_app", "settings"]

if TYPE_CHECKING:  # pragma: no cover
    from .main import app as _app
    from .main import create_app as _create_app
    from .main import settings as _settings


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module 'app' has no attribute {name!r}")

    from .main import app as fastapi_app
    from .main import create_app as factory
    from .main import settings as config

    mapping = {
        "app": fastapi_app,
        "create_app": factory,
        "settings": config,
    }
    return mapping[name]
