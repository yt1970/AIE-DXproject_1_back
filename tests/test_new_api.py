from __future__ import annotations

import json
import os
import warnings
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
    db_path = tmp_path / "test_new.sqlite3"
    uploads_dir = tmp_path / "uploads_new"
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

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning)

    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        settings_module.get_settings.cache_clear()
        clear_storage_client_cache()


def _seed_data(db: session_module.SessionLocal):
    # Create Lectures
    l1 = models.Lecture(
        name="Course A", academic_year=2024, term="Spring", session="1",
        lecture_on=date(2024, 4, 1), instructor_name="Prof A", description="Desc A"
    )
    l2 = models.Lecture(
        name="Course A", academic_year=2024, term="Spring", session="2",
        lecture_on=date(2024, 4, 8), instructor_name="Prof A", description="Desc A2"
    )
    db.add_all([l1, l2])
    db.commit()
    db.refresh(l1)
    db.refresh(l2)

    # Create Batches
    b1 = models.SurveyBatch(
        lecture_id=l1.id, batch_type="preliminary", uploaded_at=datetime(2024, 4, 1, 10, 0)
    )
    b2 = models.SurveyBatch(
        lecture_id=l2.id, batch_type="confirmed", uploaded_at=datetime(2024, 4, 8, 10, 0)
    )
    db.add_all([b1, b2])
    db.commit()
    return l1, l2, b1, b2


def test_get_courses_grouped(client: TestClient):
    # Seed data
    db = session_module.SessionLocal()
    _seed_data(db)
    db.close()

    response = client.get("/api/v1/courses")
    assert response.status_code == 200
    data = response.json()
    assert "courses" in data
    assert len(data["courses"]) == 1
    course = data["courses"][0]
    assert course["name"] == "Course A"
    assert len(course["sessions"]) == 2


def test_get_course_detail(client: TestClient):
    db = session_module.SessionLocal()
    _seed_data(db)
    db.close()

    response = client.get("/api/v1/courses/detail", params={
        "name": "Course A", "academic_year": 2024, "term": "Spring"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Course A"
    assert len(data["lectures"]) == 2
    assert data["lectures"][0]["session"] == "1"


def test_get_lecture_analysis(client: TestClient):
    db = session_module.SessionLocal()
    l1, _, _, _ = _seed_data(db)
    lid = l1.id
    db.close()

    response = client.get(f"/api/v1/lectures/{lid}/analysis", params={
        "batch_type": "preliminary"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["lecture_info"]["lecture_id"] == lid
    assert data["lecture_info"]["session"] == "1"


def test_upload_survey_multipart(client: TestClient):
    # Prepare multipart data
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
    )
    files = {"file": ("test.csv", csv_content, "text/csv")}
    data = {
        "course_name": "New Course",
        "academic_year": 2024,
        "term": "Fall",
        "session": "1",
        "lecture_date": "2024-10-01",
        "instructor_name": "Prof New",
        "batch_type": "preliminary",
        "zoom_participants": 10
    }
    
    response = client.post("/api/v1/surveys/upload", data=data, files=files)
    assert response.status_code == 202
    resp_data = response.json()
    assert "job_id" in resp_data
    assert "status_url" in resp_data
    # assert "uploaded_at" in resp_data # Removed from response


def test_search_batches(client: TestClient):
    db = session_module.SessionLocal()
    _seed_data(db)
    db.close()
    
    response = client.get("/api/v1/surveys/batches/search", params={
        "course_name": "Course A", "academic_year": 2024, "term": "Spring"
    })
    assert response.status_code == 200
    data = response.json()
    assert "batches" in data
    assert len(data["batches"]) == 2


def test_get_overall_trends(client: TestClient):
    db = session_module.SessionLocal()
    # Seed data for trends
    l1 = models.Lecture(
        name="Trend Course", academic_year=2024, term="Spring", session="1",
        lecture_on=date(2024, 4, 1), instructor_name="Prof T", description="Desc T"
    )
    l2 = models.Lecture(
        name="Trend Course", academic_year=2024, term="Spring", session="2",
        lecture_on=date(2024, 4, 8), instructor_name="Prof T", description="Desc T2"
    )
    db.add_all([l1, l2])
    db.commit()
    db.refresh(l1)
    db.refresh(l2)
    
    b1 = models.SurveyBatch(lecture_id=l1.id, batch_type="confirmed", uploaded_at=datetime(2024, 4, 1, 10, 0))
    b2 = models.SurveyBatch(lecture_id=l2.id, batch_type="confirmed", uploaded_at=datetime(2024, 4, 8, 10, 0))
    db.add_all([b1, b2])
    db.commit()
    db.refresh(b1)
    db.refresh(b2)
    
    # Summaries for Batch 1
    s1_all = models.SurveySummary(survey_batch_id=b1.id, student_attribute="all", response_count=100, nps=10.0)
    s1_stu = models.SurveySummary(survey_batch_id=b1.id, student_attribute="student", response_count=60)
    s1_cor = models.SurveySummary(survey_batch_id=b1.id, student_attribute="corporate", response_count=40)
    
    # Summaries for Batch 2
    s2_all = models.SurveySummary(survey_batch_id=b2.id, student_attribute="all", response_count=80, nps=20.0)
    s2_stu = models.SurveySummary(survey_batch_id=b2.id, student_attribute="student", response_count=50)
    s2_cor = models.SurveySummary(survey_batch_id=b2.id, student_attribute="corporate", response_count=30)
    
    db.add_all([s1_all, s1_stu, s1_cor, s2_all, s2_stu, s2_cor])
    db.commit()
    db.close()

    response = client.get("/api/v1/courses/trends", params={
        "name": "Trend Course", "academic_year": 2024, "term": "Spring", "batch_type": "confirmed"
    })
    assert response.status_code == 200
    data = response.json()
    
    trends = data["response_trends"]
    assert len(trends) == 2
    
    # Check Retention (1st session = 100, 2nd session = 80 -> 80%)
    assert trends[0]["retention_rate"] == 100.0
    assert trends[1]["retention_rate"] == 80.0
    
    # Check Breakdown
    assert trends[0]["breakdown"]["student"] == 60
    assert trends[0]["breakdown"]["corporate"] == 40
    assert trends[1]["breakdown"]["student"] == 50
    assert trends[1]["breakdown"]["corporate"] == 30
