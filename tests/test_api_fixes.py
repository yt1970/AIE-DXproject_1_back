
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.main import app
from app.db import models
from app.db import session as session_module
from app.core import settings as settings_module
from datetime import date, datetime
from pathlib import Path
import os

@pytest.fixture(name="db_session")
def fixture_db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(engine)
    
    monkeypatch.setattr(session_module, "engine", engine, raising=False)
    monkeypatch.setattr(session_module, "SessionLocal", TestingSessionLocal, raising=False)
    
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        yield db_session
    
    app.dependency_overrides[session_module.get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

def test_get_lecture_analysis_incomplete_scores(client: TestClient, db_session: Session):
    # Setup data
    lecture = models.Lecture(
        academic_year=2024,
        term="Term1",
        name="Test Course",
        session="Session1",
        lecture_on=date(2024, 10, 1),
        instructor_name="Instructor",
        description="Desc"
    )
    db_session.add(lecture)
    db_session.commit()
    db_session.refresh(lecture)

    batch = models.SurveyBatch(
        lecture_id=lecture.id,
        batch_type="confirmed",
        uploaded_at=datetime.now()
    )
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    summary = models.SurveySummary(
        survey_batch_id=batch.id,
        student_attribute="all",
        response_count=10,
        nps=10.0,
        promoter_count=5,
        passive_count=3,
        detractor_count=2,
        avg_satisfaction_overall=4.5,
        avg_content_volume=4.0,
        avg_content_understanding=3.0,
        avg_content_announcement=5.0,
        avg_instructor_overall=4.5,
        avg_instructor_time=4.0,
        avg_instructor_qa=3.0,
        avg_instructor_speaking=5.0,
        avg_self_preparation=4.0,
        avg_self_motivation=3.0,
        avg_self_future=5.0
    )
    db_session.add(summary)
    db_session.commit()

    # Call API
    response = client.get(
        f"/api/v1/lectures/{lecture.id}/analysis",
        params={"batch_type": "confirmed", "student_attribute": "all"}
    )
    assert response.status_code == 200
    data = response.json()

    # Check average_scores
    # Currently it only has overall_satisfaction, so this should fail if we expect all
    scores = {item['category_key']: item['score'] for item in data['average_scores']}
    
    expected_keys = [
        "overall_satisfaction", "learning_amount", "comprehension", "operations",
        "instructor_satisfaction", "time_management", "question_handling", "speaking_style",
        "preparation", "motivation", "future_application"
    ]
    
    missing_keys = [k for k in expected_keys if k not in scores]
    assert not missing_keys, f"Missing keys in average_scores: {missing_keys}"

    # Check NPS percentages
    # Currently hardcoded to 0.0
    nps_data = data['nps']
    assert nps_data['promoters_percentage'] == 50.0
    assert nps_data['neutrals_percentage'] == 30.0
    assert nps_data['detractors_percentage'] == 20.0
