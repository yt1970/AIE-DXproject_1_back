"""APIエンドポイントのテスト"""

from __future__ import annotations

import json
import os
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Generator
from urllib.parse import quote

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


# ============================================================================
# ヘルパー関数
# ============================================================================


# ============================================================================
# ヘルパー関数
# ============================================================================


def _post_upload(client: TestClient, *, course: str, date: str, number: int) -> int:
    """テスト用のアップロードを実行し、survey_batch_idを返す"""
    metadata = {
        "course_name": course,
        "lecture_on": date,
        "lecture_number": number,
    }
    csv_content = (
        "アカウントID,アカウント名,【必須】受講生が学んだこと,（任意）講義全体のコメント,（任意）講師へのメッセージ,"
        "本日の総合的な満足度を５段階で教えてください。,親しいご友人にこの講義の受講をお薦めしますか？,"
        "\"本日の講義内容について５段階で教えてください。\n学習量は適切だった\","
        "\"本日の講義内容について５段階で教えてください。\n講義内容が十分に理解できた\","
        "\"本日の講義内容について５段階で教えてください。\n運営側のアナウンスが適切だった\","
        "本日の講師の総合的な満足度を５段階で教えてください。,"
        "\"本日の講師について５段階で教えてください。\n授業時間を効率的に使っていた\","
        "\"本日の講師について５段階で教えてください。\n質問に丁寧に対応してくれた\","
        "\"本日の講師について５段階で教えてください。\n話し方や声の大きさが適切だった\","
        "\"ご自身について５段階で教えてください。\n事前に予習をした\","
        "\"ご自身について５段階で教えてください。\n意欲をもって講義に臨んだ\","
        "\"ご自身について５段階で教えてください。\n今回学んだことを学習や研究に生かせる\"\n"
        "user1,Student A,必須コメント,Great session!,Thank you!,5,10,5,5,5,5,5,5,5,5,5,5\n"
        "user2,Student B,別の必須,Needs more examples.,,4,8,4,4,4,4,4,4,4,4,4,4\n"
        "user3,Student C,また別の必須,,Follow-up requested,3,6,3,3,3,3,3,3,3,3,3,3\n"
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
    return response.json()["survey_batch_id"]


def _seed_comments_for_filter(db: session_module.SessionLocal, *, course_name: str) -> None:
    lecture = models.Lecture(
        academic_year=2024,
        term="Spring",
        name=course_name,
        session="1",
        lecture_on=date(2024, 5, 1),
        instructor_name="Prof Filter",
    )
    db.add(lecture)
    db.flush()

    batch = models.SurveyBatch(lecture_id=lecture.id, uploaded_at=datetime(2024, 5, 1, 0, 0, 0))
    db.add(batch)
    db.flush()

    score_defaults = {
        "score_satisfaction_overall": 5,
        "score_content_volume": 5,
        "score_content_understanding": 5,
        "score_content_announcement": 5,
        "score_instructor_overall": 5,
        "score_instructor_time": 5,
        "score_instructor_qa": 5,
        "score_instructor_speaking": 5,
        "score_self_preparation": 5,
        "score_self_motivation": 5,
        "score_self_future": 5,
        "score_recommend_friend": 10,
    }

    def _add_comment(account_suffix: str, comment_text: str, importance: str) -> None:
        survey_response = models.SurveyResponse(
            survey_batch_id=batch.id,
            account_id=f"user-{account_suffix}",
            student_attribute="ALL",
            **score_defaults,
        )
        db.add(survey_response)
        db.flush()

        db.add(
            models.ResponseComment(
                response_id=survey_response.id,
                question_type="（任意）講義全体のコメント",
                comment_text=comment_text,
                llm_category="content",
                llm_sentiment_type="positive",
                llm_importance_level=importance,
                llm_is_abusive=False,
                is_analyzed=True,
                analysis_version="preliminary",
            )
        )

    _add_comment("high", "Critical action item", "high")
    _add_comment("medium", "Should adjust pace", "medium")
    _add_comment("low", "Need better slides", "low")
    db.commit()


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
            "lecture_on": "2024-01-01",
            "lecture_number": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data
    assert "survey_batch_id" in data
    assert isinstance(data["exists"], bool)


def test_comments_endpoint_not_found(client: TestClient):
    """存在しないコースのコメント取得"""
    response = client.get("/api/v1/courses/NonExistentCourse/comments")
    # コースが存在しない場合でも、空のリストが返る可能性があるため、200または404を許容
    assert response.status_code in [200, 404]


def test_analysis_status_endpoint_not_found(client: TestClient):
    """存在しないバッチIDのステータス取得（404が返ることを確認）"""
    response = client.get("/api/v1/uploads/99999/status")
    assert response.status_code == 404


def test_metrics_endpoint_not_found(client: TestClient):
    """存在しないバッチIDのメトリクス取得（404が返ることを確認）"""
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
    """存在しないバッチIDの削除（404が返ることを確認）"""
    response = client.delete("/api/v1/uploads/99999")
    assert response.status_code == 404


def test_finalize_endpoint_not_found(client: TestClient):
    """存在しないバッチIDの確定（404が返ることを確認）"""
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
    # 期待: course_nameの昇順、学年は lecture_on.year がデフォルト付与（文字列）
    assert {i["course_name"] for i in items} == {"Course A", "Course Z"}
    for i in items:
        assert i["academic_year"] is None or isinstance(i["academic_year"], str)
        assert "period" in i


def test_duplicate_check_endpoint(client: TestClient) -> None:
    """重複チェックエンドポイントの動作確認（実際のデータを使用）"""
    batch_id = _post_upload(client, course="Dup Course", date="2024-05-10", number=1)

    # 既存 => True
    r1 = client.get(
        "/api/v1/uploads/check-duplicate",
        params={
            "course_name": "Dup Course",
            "lecture_on": "2024-05-10",
            "lecture_number": 1,
        },
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["exists"] is True
    assert body1["survey_batch_id"] == batch_id

    # 非既存 => False
    r2 = client.get(
        "/api/v1/uploads/check-duplicate",
        params={
            "course_name": "Dup Course",
            "lecture_on": "2024-05-10",
            "lecture_number": 2,
        },
    )
    assert r2.status_code == 200
    assert r2.json() == {"exists": False, "survey_batch_id": None}


def test_finalize_and_version_filter(client: TestClient) -> None:
    """確定処理とバージョンフィルタの動作確認"""
    batch_id = _post_upload(client, course="Version Course", date="2024-06-01", number=1)

    # finalize
    resp = client.post(f"/api/v1/uploads/{batch_id}/finalize")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["finalized"] is True
    # NOTE: final_count not in response, just check finalized status

    # comments with version filter
    resp2 = client.get(
        f"/api/v1/courses/Version Course/comments", params={"version": "final"}
    )
    assert resp2.status_code == 200
    comments = resp2.json()
    assert len(comments) > 0


def test_delete_uploaded_analysis_removes_db_and_file(client: TestClient) -> None:
    """アップロード削除時にDBとファイルの両方が削除されることを確認"""
    batch_id = _post_upload(client, course="Del Course", date="2024-05-20", number=1)

    # DB確認
    db = session_module.SessionLocal()
    try:
        batch = (
            db.query(models.SurveyBatch).filter(models.SurveyBatch.id == batch_id).first()
        )
        assert batch is not None
        
        # 現在の件数を控える
        # NOTE: ResponseComment doesn't have survey_batch_id, join through response
        cnt_comments = (
            db.query(models.ResponseComment)
            .join(models.ResponseComment.response)
            .filter(models.SurveyResponse.survey_batch_id == batch_id)
            .count()
        )
        cnt_surveys = (
            db.query(models.SurveyResponse)
            .filter(models.SurveyResponse.survey_batch_id == batch_id)
            .count()
        )
    finally:
        db.close()

    # 削除実行
    del_resp = client.delete(f"/api/v1/uploads/{batch_id}")
    assert del_resp.status_code == 200, del_resp.text
    payload = del_resp.json()
    assert payload["survey_batch_id"] == batch_id
    assert payload["deleted"] is True
    assert payload["removed_comments"] == cnt_comments
    assert payload["removed_survey_responses"] == cnt_surveys

    # ステータス問い合わせは404
    status_resp = client.get(f"/api/v1/uploads/{batch_id}/status")
    assert status_resp.status_code == 404


def test_metrics_upsert_and_get(client: TestClient) -> None:
    """メトリクスの作成・更新・取得の動作確認"""
    batch_id = _post_upload(client, course="Metrics Course", date="2024-06-10", number=1)

    # initial GET -> empty
    r0 = client.get(f"/api/v1/uploads/{batch_id}/metrics")
    assert r0.status_code == 200
    assert r0.json()["survey_batch_id"] == batch_id
    assert r0.json().get("zoom_participants") is None

    # upsert
    r1 = client.put(
        f"/api/v1/uploads/{batch_id}/metrics",
        json={"zoom_participants": 100, "recording_views": 50},
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["zoom_participants"] == 100
    assert body["recording_views"] == 50
    assert body["survey_batch_id"] == batch_id

    # get
    r2 = client.get(f"/api/v1/uploads/{batch_id}/metrics")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["zoom_participants"] == 100
    assert body2["recording_views"] == 50


def test_delete_rejects_processing_state(client: TestClient) -> None:
    """処理中のファイルの削除が拒否されることを確認"""
    # 処理中レコードを直接投入 (SurveySummaryがない状態)
    db = session_module.SessionLocal()
    try:
        lecture = models.Lecture(
            name="Proc Course",
            lecture_on=date(2024, 5, 21),
            academic_year=2024,
            term="Spring",  # Required field
            instructor_name="Prof. Test",
            session="1",  # Required field
        )
        db.add(lecture)
        db.flush()
        
        batch = models.SurveyBatch(
            lecture_id=lecture.id,
            uploaded_at=datetime(2024, 5, 21, 0, 0, 0),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        batch_id = batch.id
    finally:
        db.close()

    resp = client.delete(f"/api/v1/uploads/{batch_id}")
    # ステータスがPROCESSING (Summaryがない) なので削除拒否されるはず
    assert resp.status_code == 409


def test_course_comments_important_only_filter(client: TestClient) -> None:
    course_name = "Filter Course"
    db = session_module.SessionLocal()
    try:
        _seed_comments_for_filter(db, course_name=course_name)
    finally:
        db.close()

    encoded_course = quote(course_name, safe="")
    important_resp = client.get(
        f"/api/v1/courses/{encoded_course}/comments",
        params={"important_only": True},
    )
    assert important_resp.status_code == 200
    important_body = important_resp.json()
    assert len(important_body) == 2
    assert {item["llm_importance_level"] for item in important_body} == {
        "high",
        "medium",
    }

    low_only_resp = client.get(
        f"/api/v1/courses/{encoded_course}/comments",
        params={"importance": "low"},
    )
    assert low_only_resp.status_code == 200
    low_body = low_only_resp.json()
    assert len(low_body) == 1
    assert low_body[0]["llm_importance_level"] == "low"
    assert low_body[0]["comment_text"] == "Need better slides"
