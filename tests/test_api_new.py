import json
from datetime import date, datetime
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
def fixture_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_new.sqlite3"
    uploads_dir = tmp_path / "uploads_new"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_BACKEND", "local")
    monkeypatch.setenv("UPLOAD_LOCAL_DIRECTORY", str(uploads_dir))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")

    settings_module.get_settings.cache_clear()
    clear_storage_client_cache()
    from app.workers import configure_celery_app
    configure_celery_app()

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(engine)

    monkeypatch.setattr(session_module, "engine", engine, raising=False)
    monkeypatch.setattr(session_module, "SessionLocal", TestingSessionLocal, raising=False)

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

def _create_dummy_data(db, name, year, term, session, score_base):
    lec = models.Lecture(
        name=name, academic_year=year, term=term, session=session,
        lecture_on=date(year, 10, 1), instructor_name="Test Instructor"
    )
    db.add(lec)
    db.flush()
    
    batch = models.SurveyBatch(lecture_id=lec.id, batch_type="confirmed", uploaded_at=datetime.now())
    db.add(batch)
    db.flush()
    
    summary = models.SurveySummary(
        survey_batch_id=batch.id, student_attribute="all", response_count=10,
        nps=score_base * 5, promoter_count=5, passive_count=3, detractor_count=2,
        avg_satisfaction_overall=score_base,
        avg_content_volume=score_base,
        avg_content_understanding=score_base,
        avg_content_announcement=score_base,
        avg_instructor_overall=score_base,
        avg_instructor_time=score_base,
        avg_instructor_qa=score_base,
        avg_instructor_speaking=score_base,
        avg_self_preparation=score_base,
        avg_self_motivation=score_base,
        avg_self_future=score_base
    )
    db.add(summary)
    db.commit()

def test_compare_years(client):
    # Setup data
    db = session_module.SessionLocal()
    try:
        _create_dummy_data(db, "Compare Course", 2024, "Fall", "1", 4.5)
        _create_dummy_data(db, "Compare Course", 2023, "Fall", "1", 4.0)
    finally:
        db.close()
        
    resp = client.get("/api/v1/courses/compare", params={
        "name": "Compare Course",
        "current_year": 2024, "current_term": "Fall",
        "compare_year": 2023, "compare_term": "Fall",
        "batch_type": "confirmed"
    })
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["current"]["academic_year"] == 2024
    assert data["current"]["average_scores"]["overall_satisfaction"] == 4.5
    
    assert data["comparison"]["academic_year"] == 2023
    assert data["comparison"]["average_scores"]["overall_satisfaction"] == 4.0
    
    # Check difference
    # Find overall_satisfaction in score_comparison
    item = next((i for i in data["score_comparison"] if i["category_key"] == "overall_satisfaction"), None)
    assert item is not None
    assert item["difference"] == 0.5

def test_upload_validation_preliminary(client):
    csv_content = "dummy,csv"
    resp = client.post("/api/v1/surveys/upload", data={
        "course_name": "Val Course", "academic_year": 2024, "term": "Spring",
        "session": "1", "lecture_date": "2024-01-01", "instructor_name": "T",
        "batch_type": "preliminary"
        # Missing zoom_participants
    }, files={"file": ("test.csv", csv_content, "text/csv")})
    assert resp.status_code == 400
    assert "zoom_participants is required" in resp.json()["error"]["message"]

def test_upload_validation_confirmed(client):
    csv_content = "dummy,csv"
    resp = client.post("/api/v1/surveys/upload", data={
        "course_name": "Val Course", "academic_year": 2024, "term": "Spring",
        "session": "1", "lecture_date": "2024-01-01", "instructor_name": "T",
        "batch_type": "confirmed"
        # Missing recording_views
    }, files={"file": ("test.csv", csv_content, "text/csv")})
    assert resp.status_code == 400
    assert "recording_views is required" in resp.json()["error"]["message"]
