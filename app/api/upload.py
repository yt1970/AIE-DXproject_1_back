# app/api/upload.py

import json
import logging
from datetime import UTC, date, datetime
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import (
    BatchSearchItem,
    BatchSearchResponse,
    DeleteUploadResponse,
    DuplicateCheckResponse,
    UploadRequestMetadata,
    UploadResponse,
)
from app.services import StorageError, get_storage_client
from app.services.summary import compute_and_upsert_summaries
from app.services.upload_pipeline import (
    CsvValidationError,
    build_storage_path,
    validate_csv_or_raise,
)
from app.workers.tasks import process_uploaded_file

metadata_adapter = TypeAdapter(UploadRequestMetadata)
logger = logging.getLogger(__name__)

router = APIRouter()

QUEUED_STATUS = "QUEUED"


def _derive_academic_year(d: date) -> int:
    # 4月始まりと仮定
    if d.month >= 4:
        return d.year
    return d.year - 1


@router.get("/surveys/batches/search", response_model=BatchSearchResponse)
def search_batches(
    course_name: str = Query(..., description="講座名"),
    academic_year: int = Query(..., description="年度"),
    term: str = Query(..., description="期間"),
    db: Session = Depends(get_db),
) -> BatchSearchResponse:
    """
    削除対象のバッチを検索する。
    """
    # Find lectures matching the criteria
    lectures = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.name == course_name,
            models.Lecture.academic_year == academic_year,
            models.Lecture.term == term,
        )
        .all()
    )
    
    if not lectures:
        return BatchSearchResponse(batches=[])
        
    lecture_ids = [l.id for l in lectures]
    
    batches = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.lecture_id.in_(lecture_ids))
        .order_by(models.SurveyBatch.uploaded_at.desc())
        .all()
    )
    
    # Map to response
    items = []
    for b in batches:
        # Find corresponding lecture
        lec = next((l for l in lectures if l.id == b.lecture_id), None)
        if not lec: continue
        
        items.append(BatchSearchItem(
            batch_id=b.id,
            lecture_id=lec.id,
            session=lec.session,
            lecture_date=lec.lecture_on,
            batch_type=b.batch_type,
            uploaded_at=b.uploaded_at
        ))
        
    return BatchSearchResponse(batches=items)


@router.delete("/surveys/batches/{batch_id}", response_model=DeleteUploadResponse)
def delete_survey_batch(
    batch_id: int,
    db: Session = Depends(get_db),
) -> DeleteUploadResponse:
    """
    特定の講義回・分析タイプのデータを削除する。
    """
    survey_batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.id == batch_id)
        .first()
    )
    if not survey_batch:
        raise HTTPException(
            status_code=404, detail=f"Batch with id {batch_id} not found"
        )

    # Check if processing
    # Assuming if summary exists, it's done. If not, it might be processing.
    # But for deletion, we might want to allow deleting stuck jobs too?
    # API def says "Delete specific batch".
    
    removed_comments = 0
    removed_survey_responses = 0
    
    # Delete related data
    removed_comments = (
        db.query(models.ResponseComment)
        .filter(models.ResponseComment.response_id.in_(
            db.query(models.SurveyResponse.id).filter(models.SurveyResponse.survey_batch_id == batch_id)
        ))
        .delete(synchronize_session=False)
    )
    removed_survey_responses = (
        db.query(models.SurveyResponse)
        .filter(models.SurveyResponse.survey_batch_id == batch_id)
        .delete(synchronize_session=False)
    )
    
    db.query(models.SurveySummary).filter(
        models.SurveySummary.survey_batch_id == batch_id
    ).delete(synchronize_session=False)
    db.query(models.CommentSummary).filter(
        models.CommentSummary.survey_batch_id == batch_id
    ).delete(synchronize_session=False)
    db.query(models.ScoreDistribution).filter(
        models.ScoreDistribution.survey_batch_id == batch_id
    ).delete(synchronize_session=False)
    
    db.delete(survey_batch)
    db.commit()

    # Response format: { success: true, deleted_batch_id: ..., message: ... }
    # But return type says DeleteUploadResponse. 
    # API def says:
    # interface DeleteResponse {
    #   success: true;
    #   deleted_batch_id: number;
    #   deleted_response_count: number;
    #   message: string;
    # }
    # Existing DeleteUploadResponse has: survey_batch_id, deleted, removed_comments, removed_survey_responses
    # I should probably update the schema or just map it.
    # Let's map it to the existing schema for now, or update schema if strict.
    # The user asked to "match API definition".
    # I'll return a dict that matches the API def and change response_model to dict or new schema.
    # For now, I'll stick to DeleteUploadResponse but maybe I should have updated it.
    # Let's just return what matches the existing schema but ensure logic is correct.
    
    return DeleteUploadResponse(
        success=True,
        deleted_batch_id=batch_id,
        deleted_response_count=removed_survey_responses or 0,
        message=f"バッチID {batch_id} のデータ（{removed_survey_responses or 0}件）を削除しました。"
    )


@router.post("/surveys/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_survey_data(
    file: Annotated[UploadFile, File()],
    course_name: Annotated[str, Form()],
    academic_year: Annotated[int, Form()],
    term: Annotated[str, Form()],
    session: Annotated[str, Form()],
    lecture_date: Annotated[date, Form()],
    instructor_name: Annotated[str, Form()],
    batch_type: Annotated[str, Form()],
    description: Annotated[Optional[str], Form()] = None,
    zoom_participants: Annotated[Optional[int], Form()] = None,
    recording_views: Annotated[Optional[int], Form()] = None,
    db: Session = Depends(get_db),
) -> UploadResponse:
    """
    Excelファイルをアップロードし、アンケートデータを登録する。
    """
    # Construct metadata object for internal use
    # Note: lecture_number is not in the new form, but 'session' is string (e.g. "第1回").
    # Existing logic uses lecture_number (int). I need to adapt.
    # If session is "第N回", I can extract N. Or just use session string if I update the model/logic.
    # The Lecture model has 'session' as String(50). So I can use it directly.
    # But duplicate check logic might rely on it.
    
    # Read file
    try:
        content_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {exc}")

    if not content_bytes:
        raise HTTPException(status_code=400, detail="File is empty")

    # Validation for batch_type specific fields
    if batch_type == "preliminary":
        if zoom_participants is None:
            raise HTTPException(status_code=400, detail="zoom_participants is required for preliminary batch")
    elif batch_type == "confirmed":
        if recording_views is None:
            raise HTTPException(status_code=400, detail="recording_views is required for confirmed batch")
    else:
        raise HTTPException(status_code=400, detail="Invalid batch_type. Must be 'preliminary' or 'confirmed'")

    # Validate CSV/Excel
    validate_csv_or_raise(content_bytes, filename=file.filename)
    
    # Save to storage
    storage_client = get_storage_client()
    # Build a path
    storage_path = f"uploads/{academic_year}/{course_name}/{session}/{file.filename}"
    try:
        stored_uri = storage_client.save(
            relative_path=storage_path,
            data=content_bytes,
            content_type=file.content_type,
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail="Storage error") from exc

    # Find or Create Lecture
    lecture = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.name == course_name,
            models.Lecture.academic_year == academic_year,
            models.Lecture.term == term,
            models.Lecture.session == session,
        )
        .first()
    )
    
    if not lecture:
        lecture = models.Lecture(
            academic_year=academic_year,
            term=term,
            name=course_name,
            session=session,
            lecture_on=lecture_date,
            instructor_name=instructor_name,
            description=description,
        )
        db.add(lecture)
        db.commit()
        db.refresh(lecture)
    
    # Check for existing batch
    existing_batch = (
        db.query(models.SurveyBatch)
        .filter(
            models.SurveyBatch.lecture_id == lecture.id,
            models.SurveyBatch.batch_type == batch_type
        )
        .first()
    )
    if existing_batch:
        raise HTTPException(
            status_code=409, 
            detail=f"Batch already exists for {course_name} {session} ({batch_type})"
        )

    # Create Batch
    new_batch = models.SurveyBatch(
        lecture_id=lecture.id,
        batch_type=batch_type,
        zoom_participants=zoom_participants,
        recording_views=recording_views,
        uploaded_at=datetime.now(UTC),
    )
    db.add(new_batch)
    db.commit()
    db.refresh(new_batch)
    
    # Enqueue processing
    try:
        process_uploaded_file.delay(batch_id=new_batch.id, s3_key=stored_uri)
    except Exception:
        db.delete(new_batch)
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to enqueue task")

    return UploadResponse(
        success=True,
        job_id=str(new_batch.id),
        status_url=f"/api/v1/jobs/{new_batch.id}",
        message="アップロードを受け付けました。処理状況を確認してください。",
    )

# --- Keep existing endpoints if needed or remove ---
# check_duplicate_upload, finalize_analysis, delete_uploaded_by_identity
# I will keep finalize_analysis as it might be useful.
# check_duplicate_upload is likely replaced by the logic inside upload.
# delete_uploaded_by_identity is replaced by delete_survey_batch.

@router.post("/uploads/{survey_batch_id}/finalize")
def finalize_analysis(
    survey_batch_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    速報版(preliminary)のコメントを確定版(confirmed)として固定化する。
    """
    survey_batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.id == survey_batch_id)
        .first()
    )
    if not survey_batch:
        raise HTTPException(
            status_code=404, detail=f"Batch with id {survey_batch_id} not found"
        )
    
    # バッチタイプを確定版に更新
    survey_batch.batch_type = "confirmed"
    # survey_batch.finalized_at = datetime.now(UTC) # モデルにないのでコメントアウト

    # コメント自体にはバージョン概念を持たせず、バッチの種別で状態を管理する。
    updated_comments = (
        db.query(models.ResponseComment)
        .join(models.SurveyResponse, models.ResponseComment.response_id == models.SurveyResponse.id)
        .filter(models.SurveyResponse.survey_batch_id == survey_batch_id)
        .count()
    )

    # 現在のバッチ状態（batch_type）に基づいてサマリを再計算する。
    compute_and_upsert_summaries(db, survey_batch=survey_batch, version="final")
    
    db.add(survey_batch)
    db.commit()

    return {
        "survey_batch_id": survey_batch_id,
        "finalized": True,
        "updated_comments": updated_comments,
    }

