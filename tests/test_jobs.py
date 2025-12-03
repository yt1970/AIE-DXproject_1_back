from __future__ import annotations

from datetime import date, datetime

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
def fixture_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_jobs.sqlite3"
    uploads_dir = tmp_path / "uploads_jobs"
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

def test_job_status_processing(client):
    # Seed a batch without summary (processing)
    db = session_module.SessionLocal()
    l = models.Lecture(name="Job Course", academic_year=2024, term="Spring", session="1", lecture_on=date(2024, 4, 1), instructor_name="Prof Job")
    db.add(l)
    db.commit()
    b = models.SurveyBatch(lecture_id=l.id, batch_type="preliminary", uploaded_at=datetime.now())
    db.add(b)
    db.commit()
    batch_id = b.id
    db.close()

    response = client.get(f"/api/v1/jobs/{batch_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == str(batch_id)
    assert data["status"] == "processing"
    assert data["result"] is None

def test_job_status_completed(client):
    # Seed a batch with summary (completed)
    db = session_module.SessionLocal()
    l = models.Lecture(name="Job Course 2", academic_year=2024, term="Spring", session="2", lecture_on=date(2024, 4, 8), instructor_name="Prof Job")
    db.add(l)
    db.commit()
    b = models.SurveyBatch(lecture_id=l.id, batch_type="confirmed", uploaded_at=datetime.now())
    db.add(b)
    db.commit()
    
    s = models.SurveySummary(survey_batch_id=b.id, student_attribute="all", response_count=50)
    db.add(s)
    db.commit()
    batch_id = b.id
    db.close()

    response = client.get(f"/api/v1/jobs/{batch_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == str(batch_id)
    assert data["status"] == "completed"
    assert data["result"] is not None
    assert data["result"]["response_count"] == 50

def test_job_not_found(client):
    response = client.get("/api/v1/jobs/99999")
    assert response.status_code == 404
