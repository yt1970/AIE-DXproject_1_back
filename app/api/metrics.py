from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import LectureMetricsPayload, LectureMetricsResponse

router = APIRouter()


@router.get("/uploads/{survey_batch_id}/metrics", response_model=LectureMetricsResponse)
def get_metrics(
    survey_batch_id: int, db: Session = Depends(get_db)
) -> LectureMetricsResponse:
    """Return metrics for a specific survey batch."""
    batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.id == survey_batch_id)
        .first()
    )
    if not batch:
        raise HTTPException(
            status_code=404, detail=f"Batch with id {survey_batch_id} not found"
        )

    return LectureMetricsResponse(
        survey_batch_id=survey_batch_id,
        zoom_participants=batch.zoom_participants,
        recording_views=batch.recording_views,
        updated_at=batch.uploaded_at,  # Using uploaded_at as proxy for updated_at since we don't track update time
    )


@router.put("/uploads/{survey_batch_id}/metrics", response_model=LectureMetricsResponse)
def upsert_metrics(
    survey_batch_id: int,
    payload: LectureMetricsPayload,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    """Upsert metrics for a specific survey batch."""
    batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.id == survey_batch_id)
        .first()
    )
    if not batch:
        raise HTTPException(
            status_code=404, detail=f"Batch with id {survey_batch_id} not found"
        )

    batch.zoom_participants = payload.zoom_participants
    batch.recording_views = payload.recording_views
    # batch.updated_at = datetime.now(UTC) # Not in model
    db.add(batch)
    db.commit()
    db.refresh(batch)

    return LectureMetricsResponse(
        survey_batch_id=survey_batch_id,
        zoom_participants=batch.zoom_participants,
        recording_views=batch.recording_views,
        updated_at=datetime.now(UTC),
    )


def _choose_target_batch_for_lecture(
    db: Session, lecture_id: int
) -> models.SurveyBatch | None:
    """Pick confirmed batch for lecture or fallback to latest upload."""
    # Try confirmed first
    batch = (
        db.query(models.SurveyBatch)
        .filter(
            models.SurveyBatch.lecture_id == lecture_id,
            models.SurveyBatch.batch_type == "confirmed",
        )
        .order_by(models.SurveyBatch.uploaded_at.desc())
        .first()
    )
    if batch:
        return batch

    # Fallback to preliminary
    batch = (
        db.query(models.SurveyBatch)
        .filter(
            models.SurveyBatch.lecture_id == lecture_id,
            models.SurveyBatch.batch_type == "preliminary",
        )
        .order_by(models.SurveyBatch.uploaded_at.desc())
        .first()
    )
    return batch


@router.get("/lectures/{lecture_id}/metrics", response_model=LectureMetricsResponse)
def get_metrics_by_lecture(
    lecture_id: int,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    """Return metrics for a lecture by selecting a representative batch."""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    batch = _choose_target_batch_for_lecture(db, lecture_id)
    if not batch:
        return LectureMetricsResponse(survey_batch_id=0)

    return LectureMetricsResponse(
        survey_batch_id=batch.id,
        zoom_participants=batch.zoom_participants,
        recording_views=batch.recording_views,
        updated_at=batch.uploaded_at,
    )


@router.put("/lectures/{lecture_id}/metrics", response_model=LectureMetricsResponse)
def upsert_metrics_by_lecture(
    lecture_id: int,
    payload: LectureMetricsPayload,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    """Upsert metrics for a lecture by targeting the representative batch."""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    batch = _choose_target_batch_for_lecture(db, lecture_id)
    if not batch:
        raise HTTPException(
            status_code=400, detail="No survey batch found for this lecture"
        )

    batch.zoom_participants = payload.zoom_participants
    batch.recording_views = payload.recording_views
    db.add(batch)
    db.commit()
    db.refresh(batch)

    return LectureMetricsResponse(
        survey_batch_id=batch.id,
        zoom_participants=batch.zoom_participants,
        recording_views=batch.recording_views,
        updated_at=datetime.now(UTC),
    )
