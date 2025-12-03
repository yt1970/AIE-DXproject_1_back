from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import models
from app.db import session as session_module

def _create_dashboard_data(db):
    # Create Lecture
    lecture1 = models.Lecture(
        name="Dashboard Course",
        academic_year=2024,
        term="Spring",
        session="第1回",
        lecture_on=date(2024, 4, 1),
        instructor_name="Prof. Dashboard"
    )
    db.add(lecture1)
    db.flush()
    
    lecture2 = models.Lecture(
        name="Dashboard Course",
        academic_year=2024,
        term="Spring",
        session="第2回",
        lecture_on=date(2024, 4, 8),
        instructor_name="Prof. Dashboard"
    )
    db.add(lecture2)
    db.flush()

    # Create Batches
    batch1 = models.SurveyBatch(
        lecture_id=lecture1.id,
        batch_type="confirmed",
        uploaded_at=datetime(2024, 4, 2, 10, 0, 0)
    )
    db.add(batch1)
    db.flush()
    
    batch2 = models.SurveyBatch(
        lecture_id=lecture2.id,
        batch_type="preliminary",
        uploaded_at=datetime(2024, 4, 9, 10, 0, 0)
    )
    db.add(batch2)
    db.flush()

    # Create Summaries
    summary1 = models.SurveySummary(
        survey_batch_id=batch1.id,
        student_attribute="all",
        response_count=10,
        nps=20.0,
        promoter_count=5,
        passive_count=3,
        detractor_count=2,
        avg_satisfaction_overall=4.5
    )
    db.add(summary1)
    
    summary2 = models.SurveySummary(
        survey_batch_id=batch2.id,
        student_attribute="all",
        response_count=5,
        nps=10.0,
        promoter_count=2,
        passive_count=2,
        detractor_count=1,
        avg_satisfaction_overall=4.0
    )
    db.add(summary2)
    db.commit()
    
    return lecture1.id, lecture2.id

def test_dashboard_overview_success(client: TestClient):
    # Setup data
    db = session_module.SessionLocal()
    try:
        lec1_id, lec2_id = _create_dashboard_data(db)
    finally:
        db.close()

    # Test Overview
    resp = client.get(f"/api/v1/dashboard/{lec1_id}/overview")
    assert resp.status_code == 200
    data = resp.json()
    
    # Check Timeline (should have 2 items)
    assert len(data["timeline"]) == 2
    # Check sorting (by lecture_on/session)
    assert data["timeline"][0]["lecture_number"] == "第1回"
    assert data["timeline"][1]["lecture_number"] == "第2回"
    
    # Check Aggregates
    # NPS: (5+2 - (2+1)) / (10+5) * 100 = (4 / 15) * 100 = 26.7
    # Wait, dashboard overview aggregates ALL batches?
    # _aggregate_nps sums up counts.
    # Promoters: 5+2=7. Detractors: 2+1=3. Total: 15.
    # Score: (7-3)/15 * 100 = 4/15 * 100 = 26.66... -> 26.7
    assert data["nps"]["score"] == 26.7
    assert data["nps"]["total"] == 15

def test_dashboard_per_lecture_success(client: TestClient):
    # Setup data (reuse if possible, but clean DB per test usually)
    # Since tests run in isolation or transaction rollback, we create data again or rely on fixture.
    # Here we create data again.
    db = session_module.SessionLocal()
    try:
        lec1_id, lec2_id = _create_dashboard_data(db)
    finally:
        db.close()

    # Test Per Lecture
    resp = client.get(f"/api/v1/dashboard/{lec1_id}/per_lecture")
    assert resp.status_code == 200
    data = resp.json()
    
    assert "lectures" in data
    assert len(data["lectures"]) == 2
    
    l1 = next(l for l in data["lectures"] if l["lecture_number"] == "第1回")
    assert l1["nps"]["score"] == 20.0
    assert l1["scores"]["overall_satisfaction"] == 4.5
    
    l2 = next(l for l in data["lectures"] if l["lecture_number"] == "第2回")
    assert l2["nps"]["score"] == 10.0
    assert l2["scores"]["overall_satisfaction"] == 4.0
