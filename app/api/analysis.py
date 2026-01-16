from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import JobResult, JobStatusResponse

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    アップロード処理などの非同期ジョブの進行状況と結果を取得する。
    job_id は現在は survey_batch_id と同じ。
    """
    try:
        batch_id = int(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found") from None

    survey_batch = db.query(models.SurveyBatch).filter(models.SurveyBatch.id == batch_id).first()

    if not survey_batch:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Check if summary exists to determine completion
    summary = (
        db.query(models.SurveySummary)
        .filter(
            models.SurveySummary.survey_batch_id == batch_id,
            models.SurveySummary.student_attribute == "all",  # Assuming 'all' summary is always created
        )
        .first()
    )

    status = "completed" if summary else "processing"
    # Note: "queued" or "failed" logic would require more state tracking in DB.
    # For now, we assume processing if batch exists but summary doesn't.

    result = None
    if status == "completed" and summary:
        result = JobResult(
            lecture_id=survey_batch.lecture_id,
            batch_id=survey_batch.id,
            response_count=summary.response_count,
        )

    return JobStatusResponse(
        job_id=str(survey_batch.id),
        status=status,
        created_at=survey_batch.uploaded_at,
        result=result,
    )
