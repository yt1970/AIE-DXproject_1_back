from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import LectureMetricsPayload, LectureMetricsResponse

router = APIRouter()


@router.get("/uploads/{file_id}/metrics", response_model=LectureMetricsResponse)
def get_metrics(file_id: int, db: Session = Depends(get_db)) -> LectureMetricsResponse:
    uploaded = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.file_id == file_id)
        .first()
    )
    if not uploaded:
        raise HTTPException(status_code=404, detail=f"File with id {file_id} not found")

    metrics = (
        db.query(models.LectureMetrics)
        .filter(models.LectureMetrics.file_id == file_id)
        .first()
    )
    if not metrics:
        return LectureMetricsResponse(file_id=file_id)

    return LectureMetricsResponse(
        file_id=file_id,
        zoom_participants=metrics.zoom_participants,
        recording_views=metrics.recording_views,
        updated_at=metrics.updated_at,
    )


@router.put("/uploads/{file_id}/metrics", response_model=LectureMetricsResponse)
def upsert_metrics(
    file_id: int,
    payload: LectureMetricsPayload,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    uploaded = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.file_id == file_id)
        .first()
    )
    if not uploaded:
        raise HTTPException(status_code=404, detail=f"File with id {file_id} not found")

    metrics = (
        db.query(models.LectureMetrics)
        .filter(models.LectureMetrics.file_id == file_id)
        .first()
    )
    if not metrics:
        metrics = models.LectureMetrics(file_id=file_id)

    metrics.zoom_participants = payload.zoom_participants
    metrics.recording_views = payload.recording_views
    metrics.updated_at = datetime.utcnow()
    db.add(metrics)
    db.commit()
    db.refresh(metrics)

    return LectureMetricsResponse(
        file_id=file_id,
        zoom_participants=metrics.zoom_participants,
        recording_views=metrics.recording_views,
        updated_at=metrics.updated_at,
    )


