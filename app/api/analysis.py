from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import AnalysisStatusResponse

router = APIRouter()


@router.get("/uploads/{survey_batch_id}/status", response_model=AnalysisStatusResponse)
def get_analysis_status(
    survey_batch_id: int,
    db: Session = Depends(get_db),
):
    """指定されたバッチIDの分析ステータスを返す。"""
    survey_batch = db.query(models.SurveyBatch).filter(models.SurveyBatch.id == survey_batch_id).first()

    if not survey_batch:
        raise HTTPException(
            status_code=404, detail=f"Batch ID {survey_batch_id} not found"
        )

    # Check if summary exists to determine completion
    summary = db.query(models.SurveySummary).filter(
        models.SurveySummary.survey_batch_id == survey_batch_id,
        models.SurveySummary.student_attribute == 'ALL' # Assuming 'ALL' summary is always created
    ).first()

    status = "COMPLETED" if summary else "PROCESSING"
    
    # Count processed comments
    processed_count = (
        db.query(models.ResponseComment)
        .filter(models.ResponseComment.survey_batch_id == survey_batch_id)
        .count()
    )
    
    # Total comments is unknown during processing without extra storage, 
    # so we assume it matches processed_count if completed, or just return processed_count.
    total_comments = processed_count

    return AnalysisStatusResponse(
        survey_batch_id=survey_batch_id,
        status=status,
        total_comments=total_comments,
        processed_count=processed_count,
        task_id=None, # Not tracked in DB
        queued_at=survey_batch.uploaded_at,
        processing_started_at=None, # Not tracked in DB
        processing_completed_at=None, # Not tracked in DB
        error_message=None, # Not tracked in DB
    )
