import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as app_main
from app.core import settings as settings_module
from app.db import models
from app.db import session as session_module
from app.services.storage import clear_storage_client_cache

@pytest.fixture(name="client")
def fixture_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """テスト用のクライアントを作成（データベースセットアップ済み）"""
    db_path = tmp_path / "test.sqlite3"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_BACKEND", "local")
    monkeypatch.setenv("UPLOAD_LOCAL_DIRECTORY", str(uploads_dir))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "true")
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")

    settings_module.get_settings.cache_clear()
    clear_storage_client_cache()
    from app.workers import configure_celery_app

    configure_celery_app()

    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(engine)

    monkeypatch.setattr(session_module, "engine", engine, raising=False)
    monkeypatch.setattr(
        session_module, "SessionLocal", TestingSessionLocal, raising=False
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = app_main.create_app()
    app.dependency_overrides[session_module.get_db] = override_get_db

    warnings.filterwarnings(
        "ignore",
        message="The 'app' shortcut is now deprecated",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message="Please use `import python_multipart` instead.",
        category=PendingDeprecationWarning,
    )

    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        settings_module.get_settings.cache_clear()
        clear_storage_client_cache()
