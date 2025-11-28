from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import AnalysisStatusResponse

router = APIRouter()


@router.get("/uploads/{uploaded_file_id}/status", response_model=AnalysisStatusResponse)
def get_analysis_status(
    uploaded_file_id: int,
    db: Session = Depends(get_db),
):
    """指定されたファイルIDの分析ステータスを返す。"""
    uploaded_file = db.query(models.UploadedFile).filter(models.UploadedFile.id == uploaded_file_id).first()

    if not uploaded_file:
        raise HTTPException(
            status_code=404, detail=f"ファイルID {uploaded_file_id} が見つかりません"
        )

    processed_count = uploaded_file.processed_rows
    if processed_count is None:
        processed_count = (
            db.query(models.Comment).filter(models.Comment.uploaded_file_id == uploaded_file_id).count()
        )
    total_comments = uploaded_file.total_rows
    if total_comments is None:
        total_comments = processed_count

    return AnalysisStatusResponse(
        uploaded_file_id=uploaded_file_id,
        status=uploaded_file.status,
        total_comments=total_comments,
        processed_count=processed_count,
        task_id=uploaded_file.task_id,
        queued_at=uploaded_file.uploaded_at,
        processing_started_at=uploaded_file.processing_started_at,
        processing_completed_at=uploaded_file.processing_completed_at,
        error_message=uploaded_file.error_message,
    )
