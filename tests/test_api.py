"""APIエンドポイントのテスト"""

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


@pytest.fixture(name="client")
def fixture_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
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

    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        settings_module.get_settings.cache_clear()
        clear_storage_client_cache()


# ============================================================================
# ヘルパー関数
# ============================================================================


def _post_upload(client: TestClient, *, course: str, date: str, number: int) -> int:
    """テスト用のアップロードを実行し、file_idを返す"""
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


# ============================================================================
# 基本動作確認テスト
# ============================================================================


def test_health_endpoint(client: TestClient):
    """ヘルスチェックエンドポイントの動作確認"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
    assert "app_name" in data


def test_courses_list_endpoint(client: TestClient):
    """コース一覧エンドポイントの動作確認（空のリストでもOK）"""
    response = client.get("/api/v1/courses")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_courses_list_with_params(client: TestClient):
    """コース一覧エンドポイントのパラメータ付きリクエスト"""
    response = client.get(
        "/api/v1/courses", params={"name": "test", "sort_by": "course_name"}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_lectures_list_endpoint(client: TestClient):
    """講義一覧エンドポイントの動作確認"""
    response = client.get("/api/v1/lectures")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_lectures_metadata_endpoint(client: TestClient):
    """講義メタデータエンドポイントの動作確認"""
    response = client.get("/api/v1/lectures/metadata")
    assert response.status_code == 200
    data = response.json()
    assert "courses" in data
    assert "years" in data
    assert "terms" in data
    assert isinstance(data["courses"], list)
    assert isinstance(data["years"], list)
    assert isinstance(data["terms"], list)


def test_upload_check_duplicate_endpoint(client: TestClient):
    """重複チェックエンドポイントの動作確認"""
    response = client.get(
        "/api/v1/uploads/check-duplicate",
        params={
            "course_name": "Test Course",
            "lecture_date": "2024-01-01",
            "lecture_number": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data
    assert "file_id" in data
    assert isinstance(data["exists"], bool)


def test_comments_endpoint_not_found(client: TestClient):
    """存在しないコースのコメント取得"""
    response = client.get("/api/v1/courses/NonExistentCourse/comments")
    # コースが存在しない場合でも、空のリストが返る可能性があるため、200または404を許容
    assert response.status_code in [200, 404]


def test_analysis_status_endpoint_not_found(client: TestClient):
    """存在しないファイルIDのステータス取得（404が返ることを確認）"""
    response = client.get("/api/v1/uploads/99999/status")
    assert response.status_code == 404


def test_metrics_endpoint_not_found(client: TestClient):
    """存在しないファイルIDのメトリクス取得（404が返ることを確認）"""
    response = client.get("/api/v1/uploads/99999/metrics")
    assert response.status_code == 404


def test_dashboard_overview_endpoint_not_found(client: TestClient):
    """存在しない講義IDのダッシュボード取得（404が返ることを確認）"""
    response = client.get("/api/v1/dashboard/99999/overview")
    assert response.status_code == 404


def test_dashboard_per_lecture_endpoint_not_found(client: TestClient):
    """存在しない講義IDの講義ごとダッシュボード取得（空データが返ることを確認）"""
    response = client.get("/api/v1/dashboard/99999/per_lecture")
    # 存在しない講義IDでも空データを返す実装のため200を期待
    assert response.status_code == 200
    data = response.json()
    assert "lectures" in data
    assert data["lectures"] == []


def test_lecture_metrics_endpoint_not_found(client: TestClient):
    """存在しない講義IDのメトリクス取得（404が返ることを確認）"""
    response = client.get("/api/v1/lectures/99999/metrics")
    assert response.status_code == 404


def test_delete_upload_endpoint_not_found(client: TestClient):
    """存在しないファイルIDの削除（404が返ることを確認）"""
    response = client.delete("/api/v1/uploads/99999")
    assert response.status_code == 404


def test_finalize_endpoint_not_found(client: TestClient):
    """存在しないファイルIDの確定（404が返ることを確認）"""
    response = client.post("/api/v1/uploads/99999/finalize")
    assert response.status_code == 404


def test_api_routes_registered(client: TestClient):
    """主要なAPIルートが登録されていることを確認"""
    # OpenAPIスキーマを取得してルートを確認
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi_schema = response.json()
    paths = openapi_schema.get("paths", {})

    # 主要なエンドポイントが存在することを確認
    expected_paths = [
        "/health",
        "/api/v1/courses",
        "/api/v1/lectures",
        "/api/v1/uploads/check-duplicate",
    ]

    for path in expected_paths:
        assert path in paths, f"Path {path} not found in OpenAPI schema"


# ============================================================================
# 統合テスト
# ============================================================================


def test_courses_list_returns_distinct_sorted(client: TestClient) -> None:
    """コース一覧が重複なく、ソートされて返ることを確認"""
    _post_upload(client, course="Course Z", date="2024-05-01", number=1)
    _post_upload(client, course="Course A", date="2024-05-02", number=1)
    # 重複する講座名
    _post_upload(client, course="Course A", date="2024-05-03", number=2)

    resp = client.get("/api/v1/courses")
    assert resp.status_code == 200
    items = resp.json()
    # 期待: course_nameの昇順、学年は lecture_date.year がデフォルト付与（文字列）
    assert {i["course_name"] for i in items} == {"Course A", "Course Z"}
    for i in items:
        assert i["academic_year"] is None or isinstance(i["academic_year"], str)
        assert "period" in i


def test_duplicate_check_endpoint(client: TestClient) -> None:
    """重複チェックエンドポイントの動作確認（実際のデータを使用）"""
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


def test_finalize_and_version_filter(client: TestClient) -> None:
    """確定処理とバージョンフィルタの動作確認"""
    file_id = _post_upload(client, course="Version Course", date="2024-06-01", number=1)

    # finalize
    resp = client.post(f"/api/v1/uploads/{file_id}/finalize")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["finalized"] is True
    assert payload["final_count"] > 0

    # comments with version filter
    resp2 = client.get(
        f"/api/v1/courses/Version Course/comments", params={"version": "final"}
    )
    assert resp2.status_code == 200
    comments = resp2.json()
    assert len(comments) > 0


def test_delete_uploaded_analysis_removes_db_and_file(client: TestClient) -> None:
    """アップロード削除時にDBとファイルの両方が削除されることを確認"""
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
            db.query(models.Comment).filter(models.Comment.file_id == file_id).count()
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


def test_metrics_upsert_and_get(client: TestClient) -> None:
    """メトリクスの作成・更新・取得の動作確認"""
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


def test_delete_rejects_processing_state(client: TestClient) -> None:
    """処理中のファイルの削除が拒否されることを確認"""
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
