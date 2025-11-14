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

def _choose_target_file_for_lecture(db: Session, lecture_id: int) -> int | None:
    files = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.lecture_id == lecture_id)
        .all()
    )
    if not files:
        return None
    finalized = [f for f in files if f.finalized_at is not None]
    if finalized:
        chosen = max(finalized, key=lambda f: f.finalized_at)
    else:
        chosen = max(files, key=lambda f: f.upload_timestamp)
    return chosen.file_id


@router.get("/lectures/{lecture_id}/metrics", response_model=LectureMetricsResponse)
def get_metrics_by_lecture(
    lecture_id: int,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    file_id = _choose_target_file_for_lecture(db, lecture_id)
    if file_id is None:
        return LectureMetricsResponse(file_id=0)
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


@router.put("/lectures/{lecture_id}/metrics", response_model=LectureMetricsResponse)
def upsert_metrics_by_lecture(
    lecture_id: int,
    payload: LectureMetricsPayload,
    db: Session = Depends(get_db),
) -> LectureMetricsResponse:
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