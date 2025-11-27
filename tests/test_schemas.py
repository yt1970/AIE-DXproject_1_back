from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.comment import (
    CommentAnalysisSchema,
    DuplicateCheckResponse,
    LectureMetricsResponse,
    UploadRequestMetadata,
)
from app.schemas.course import LectureCategory, LectureCreate, LectureUpdate


def test_lecture_create_accepts_enum_categories() -> None:
    lecture = LectureCreate(
        course_name="Advanced Robotics",
        academic_year=2025,
        period="Spring A",
        category=LectureCategory.講義資料,
    )

    assert lecture.category is LectureCategory.講義資料
    assert lecture.course_name == "Advanced Robotics"


def test_lecture_create_rejects_invalid_category() -> None:
    with pytest.raises(ValidationError):
        LectureCreate(
            course_name="Systems Engineering",
            academic_year=2025,
            period="Fall B",
            category="unsupported",  # type: ignore[arg-type]
        )


def test_lecture_update_allows_partial_payload() -> None:
    update = LectureUpdate(period="Intensive", category=LectureCategory.運営)

    assert update.model_dump(exclude_none=True) == {
        "period": "Intensive",
        "category": LectureCategory.運営,
    }


def test_upload_request_metadata_parses_date_and_defaults() -> None:
    payload = UploadRequestMetadata(
        course_name="AI Ethics",
        lecture_date="2024-04-01",
        lecture_number=3,
    )

    assert payload.lecture_date == date(2024, 4, 1)
    assert payload.lecture_id is None
    assert payload.uploader_id is None


def test_comment_analysis_schema_computed_fields_and_exclusion() -> None:
    survey = SimpleNamespace(
        score_satisfaction_overall=4,
        score_satisfaction_content_understanding=5,
        score_satisfaction_instructor_overall=3,
    )
    comment = SimpleNamespace(
        account_id="user-1",
        account_name="Alice",
        question_text="How was the lecture?",
        comment_text="Great session!",
        survey_response=survey,
    )

    schema = CommentAnalysisSchema.model_validate(comment)
    dumped = schema.model_dump()

    assert schema.score_satisfaction_overall == 4
    assert schema.score_satisfaction_content_understanding == 5
    assert schema.score_satisfaction_instructor_overall == 3
    assert "survey_response" not in dumped


def test_duplicate_check_response_defaults() -> None:
    response = DuplicateCheckResponse(exists=False)
    assert response.file_id is None


def test_lecture_metrics_response_extends_payload() -> None:
    response = LectureMetricsResponse(
        file_id=99,
        zoom_participants=120,
        recording_views=45,
        updated_at=datetime(2024, 5, 1, 12, 30),
    )

    assert response.file_id == 99
    assert response.zoom_participants == 120
    assert response.updated_at == datetime(2024, 5, 1, 12, 30)
