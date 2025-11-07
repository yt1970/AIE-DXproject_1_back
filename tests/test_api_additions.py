from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
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


def _post_upload(client: TestClient, *, course: str, date: str, number: int) -> int:
    metadata = {
        "course_name": course,
        "lecture_date": date,
        "lecture_number": number,
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
    return response.json()["file_id"]


def test_courses_list_returns_distinct_sorted(integration_client: TestClient) -> None:
    client = integration_client

    _post_upload(client, course="Course Z", date="2024-05-01", number=1)
    _post_upload(client, course="Course A", date="2024-05-02", number=1)
    # 重複する講座名
    _post_upload(client, course="Course A", date="2024-05-03", number=2)

    resp = client.get("/api/v1/courses")
    assert resp.status_code == 200
    assert resp.json() == ["Course A", "Course Z"]


def test_duplicate_check_endpoint(integration_client: TestClient) -> None:
    client = integration_client

    file_id = _post_upload(client, course="Dup Course", date="2024-05-10", number=1)

    # 既存 => True
    r1 = client.get(
        "/api/v1/uploads/check-duplicate",
        params={
            "course_name": "Dup Course",
            "lecture_date": "2024-05-10",
            "lecture_number": 1,
        },
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["exists"] is True
    assert body1["file_id"] == file_id

    # 非既存 => False
    r2 = client.get(
        "/api/v1/uploads/check-duplicate",
        params={
            "course_name": "Dup Course",
            "lecture_date": "2024-05-10",
            "lecture_number": 2,
        },
    )
    assert r2.status_code == 200
    assert r2.json() == {"exists": False, "file_id": None}


def test_finalize_and_version_filter(integration_client: TestClient) -> None:
    client = integration_client

    file_id = _post_upload(client, course="Version Course", date="2024-06-01", number=1)

    # finalize
    resp = client.post(f"/api/v1/uploads/{file_id}/finalize")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["finalized"] is True
    assert payload["final_count"] > 0

    # comments with version filter
    resp2 = client.get(f"/api/v1/courses/Version Course/comments", params={"version": "final"})
    assert resp2.status_code == 200
    comments = resp2.json()
    assert len(comments) > 0


def test_delete_uploaded_analysis_removes_db_and_file(
    integration_client: TestClient,
) -> None:
    client = integration_client

    file_id = _post_upload(client, course="Del Course", date="2024-05-20", number=1)

    # s3_key 取得と現存確認
    db = session_module.SessionLocal()
    try:
        uploaded = (
            db.query(models.UploadedFile)
            .filter(models.UploadedFile.file_id == file_id)
            .first()
        )
        assert uploaded is not None
        s3_key = uploaded.s3_key
        assert s3_key and s3_key.startswith("local://")
        relative = s3_key.split("://", 1)[1]
        base_dir = Path(os.environ["UPLOAD_LOCAL_DIRECTORY"]).resolve()
        file_path = (base_dir / Path(relative)).resolve()
        assert file_path.exists()

        # 現在の件数を控える
        cnt_comments = (
            db.query(models.Comment)
            .filter(models.Comment.file_id == file_id)
            .count()
        )
        cnt_surveys = (
            db.query(models.SurveyResponse)
            .filter(models.SurveyResponse.file_id == file_id)
            .count()
        )
    finally:
        db.close()

    # 削除実行
    del_resp = client.delete(f"/api/v1/uploads/{file_id}")
    assert del_resp.status_code == 200, del_resp.text
    payload = del_resp.json()
    assert payload["file_id"] == file_id
    assert payload["deleted"] is True
    assert payload["removed_comments"] == cnt_comments
    assert payload["removed_survey_responses"] == cnt_surveys

    # 物理ファイルが削除されている
    assert not file_path.exists()

    # ステータス問い合わせは404
    status_resp = client.get(f"/api/v1/uploads/{file_id}/status")
    assert status_resp.status_code == 404


def test_metrics_upsert_and_get(integration_client: TestClient) -> None:
    client = integration_client

    file_id = _post_upload(client, course="Metrics Course", date="2024-06-10", number=1)

    # initial GET -> empty
    r0 = client.get(f"/api/v1/uploads/{file_id}/metrics")
    assert r0.status_code == 200
    assert r0.json()["file_id"] == file_id
    assert r0.json().get("zoom_participants") is None

    # upsert
    r1 = client.put(
        f"/api/v1/uploads/{file_id}/metrics",
        json={"zoom_participants": 120, "recording_views": 345},
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["zoom_participants"] == 120
    assert body["recording_views"] == 345
    assert body["file_id"] == file_id

    # get
    r2 = client.get(f"/api/v1/uploads/{file_id}/metrics")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["zoom_participants"] == 120
    assert body2["recording_views"] == 345


def test_delete_rejects_processing_state(integration_client: TestClient) -> None:
    client = integration_client

    # 処理中レコードを直接投入
    db = session_module.SessionLocal()
    try:
        rec = models.UploadedFile(
            course_name="Proc Course",
            lecture_date=date(2024, 5, 21),
            lecture_number=1,
            status="PROCESSING",
            s3_key="local://dummy/path.csv",
            upload_timestamp=datetime(2024, 5, 21, 0, 0, 0),
            original_filename="path.csv",
            content_type="text/csv",
            total_rows=0,
            processed_rows=0,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        rec_id = rec.file_id
    finally:
        db.close()

    resp = client.delete(f"/api/v1/uploads/{rec_id}")
    assert resp.status_code == 409

