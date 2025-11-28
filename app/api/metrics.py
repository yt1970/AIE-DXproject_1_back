from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import LectureMetricsPayload, LectureMetricsResponse

router = APIRouter()


@router.get("/uploads/{uploaded_file_id}/metrics", response_model=LectureMetricsResponse)
def get_metrics(uploaded_file_id: int, db: Session = Depends(get_db)) -> LectureMetricsResponse:
    """Return metrics for a specific uploaded file."""
    uploaded = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.id == uploaded_file_id)
        .first()
    )
    if not uploaded:
        raise HTTPException(status_code=404, detail=f"File with id {uploaded_file_id} not found")

    metrics = (
        db.query(models.LectureMetrics)
        .filter(models.LectureMetrics.uploaded_file_id == uploaded_file_id)
        .first()
    )
    if not metrics:
        return LectureMetricsResponse(uploaded_file_id=uploaded_file_id)

    return LectureMetricsResponse(
        uploaded_file_id=uploaded_file_id,
        zoom_participants=metrics.zoom_participants,
        recording_views=metrics.recording_views,
        updated_at=metrics.updated_at,
    )


@router.put("/uploads/{uploaded_file_id}/metrics", response_model=LectureMetricsResponse)
def upsert_metrics(
    uploaded_file_id: int,
    payload: LectureMetricsPayload,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    """Upsert metrics for a specific uploaded file."""
    uploaded = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.id == uploaded_file_id)
        .first()
    )
    if not uploaded:
        raise HTTPException(status_code=404, detail=f"File with id {uploaded_file_id} not found")

    metrics = (
        db.query(models.LectureMetrics)
        .filter(models.LectureMetrics.uploaded_file_id == uploaded_file_id)
        .first()
    )
    if not metrics:
        metrics = models.LectureMetrics(uploaded_file_id=uploaded_file_id)

    metrics.zoom_participants = payload.zoom_participants
    metrics.recording_views = payload.recording_views
    metrics.updated_at = datetime.now(UTC)
    db.add(metrics)
    db.commit()
    db.refresh(metrics)

    return LectureMetricsResponse(
        uploaded_file_id=uploaded_file_id,
        zoom_participants=metrics.zoom_participants,
        recording_views=metrics.recording_views,
        updated_at=metrics.updated_at,
    )


def _choose_target_file_for_lecture(db: Session, lecture_id: int) -> int | None:
    """Pick finalized file for lecture or fallback to latest upload in one query."""
    row = (
        db.query(models.UploadedFile.id)
        .filter(models.UploadedFile.lecture_id == lecture_id)
        .order_by(
            models.UploadedFile.finalized_at.is_(None),
            models.UploadedFile.finalized_at.desc(),
            models.UploadedFile.uploaded_at.desc(),
        )
        .first()
    )
    if not row:
        return None
    # row is a tuple when selecting a single column; index for clarity
    return int(row[0])


@router.get("/lectures/{lecture_id}/metrics", response_model=LectureMetricsResponse)
def get_metrics_by_lecture(
    lecture_id: int,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    """Return metrics for a lecture by selecting a representative file."""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    file_id = _choose_target_file_for_lecture(db, lecture_id)
    if file_id is None:
        return LectureMetricsResponse(uploaded_file_id=0)
    metrics = (
        db.query(models.LectureMetrics)
        .filter(models.LectureMetrics.file_id == file_id)
        .first()
    )
    if not metrics:
        return LectureMetricsResponse(uploaded_file_id=file_id)
    return LectureMetricsResponse(
        uploaded_file_id=file_id,
        zoom_participants=metrics.zoom_participants,
        recording_views=metrics.recording_views,
        updated_at=metrics.updated_at,
    )


@router.put("/lectures/{lecture_id}/metrics", response_model=LectureMetricsResponse)
def upsert_metrics_by_lecture(
    lecture_id: int,
    payload: LectureMetricsPayload,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    """Upsert metrics for a lecture by targeting the representative file."""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    file_id = _choose_target_file_for_lecture(db, lecture_id)
    if file_id is None:
        raise HTTPException(
            status_code=400, detail="No uploaded file found for this lecture"
        )
    metrics = (
        db.query(models.LectureMetrics)
        .filter(models.LectureMetrics.uploaded_file_id == file_id)
        .first()
    )
    if not metrics:
        metrics = models.LectureMetrics(uploaded_file_id=file_id)
    metrics.zoom_participants = payload.zoom_participants
    metrics.recording_views = payload.recording_views
    metrics.updated_at = datetime.now(UTC)
    db.add(metrics)
    db.commit()
    db.refresh(metrics)
    return LectureMetricsResponse(
        uploaded_file_id=file_id,
        zoom_participants=metrics.zoom_participants,
        recording_views=metrics.recording_views,
        updated_at=metrics.updated_at,
    )
