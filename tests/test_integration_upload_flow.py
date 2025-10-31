from __future__ import annotations

import json
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as app_main
from app.core import settings as settings_module
from app.db import models
from app.db import session as session_module
from app.services.storage import clear_storage_client_cache


@pytest.fixture(name="integration_client")
def fixture_integration_client(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    db_path = tmp_path / "integration.sqlite3"
    uploads_dir = tmp_path / "uploads"

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

    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        settings_module.get_settings.cache_clear()
        clear_storage_client_cache()


def test_upload_status_and_comments_flow(
    integration_client: TestClient,
) -> None:
    client = integration_client

    metadata = {
        "course_name": "IntegrationCourse",
        "lecture_date": "2024-05-01",
        "lecture_number": 1,
    }
    csv_content = (
        "【必須】受講生が学んだこと,（任意）講義全体のコメント,（任意）講師へのメッセージ\n"
        "必須コメント,Great session!,Thank you!\n"
        "別の必須,Needs more examples.,\n"
        "また別の必須,,Follow-up requested\n"
    )

    response = client.post(
        "/api/v1/uploads",
        data={"metadata": json.dumps(metadata)},
        files={
            "file": (
                "feedback.csv",
                csv_content.encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200, response.text
    response_body = response.json()
    file_id = response_body["file_id"]
    assert response_body["status_url"] == f"/api/v1/uploads/{file_id}/status"

    status_response = client.get(f"/api/v1/uploads/{file_id}/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "COMPLETED"
    assert status_payload["total_comments"] == 4
    assert status_payload["processed_count"] == 4
    assert status_payload["task_id"]
    assert status_payload["queued_at"]
    assert status_payload["processing_started_at"]
    assert status_payload["processing_completed_at"]
    assert status_payload["error_message"] is None

    comments_response = client.get(
        f"/api/v1/courses/{metadata['course_name']}/comments"
    )
    assert comments_response.status_code == 200
    comments = comments_response.json()
    assert len(comments) == 4

    received_texts = {comment["comment_text"] for comment in comments}
    assert received_texts == {
        "Great session!",
        "Thank you!",
        "Needs more examples.",
        "Follow-up requested",
    }

    for comment in comments:
        assert comment["llm_category"] == "その他"
        assert comment["llm_sentiment"] == "neutral"
        assert comment["llm_importance_level"] == "low"
        assert comment["llm_importance_score"] == 0.0
        assert comment["llm_risk_level"] == "none"
        assert comment["llm_summary"] == comment["comment_text"]


def test_upload_rejects_duplicate_headers(integration_client: TestClient) -> None:
    client = integration_client

    metadata = {
        "course_name": "IntegrationCourse",
        "lecture_date": "2024-05-01",
        "lecture_number": 2,
    }
    csv_content = (
        "（任意）講義全体のコメント, （任意）講義全体のコメント\n"
        "Great session!,Duplicate header test\n"
    )

    response = client.post(
        "/api/v1/uploads",
        data={"metadata": json.dumps(metadata)},
        files={
            "file": (
                "duplicate.csv",
                csv_content.encode("utf-8"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 400
    assert "duplicate column names" in response.json()["detail"]
