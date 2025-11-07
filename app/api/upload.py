# app/api/upload.py

import json
import logging
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import (
    DeleteUploadResponse,
    DuplicateCheckResponse,
    UploadRequestMetadata,
    UploadResponse,
)
from app.services import StorageError, get_storage_client
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
@router.get("/uploads/check-duplicate", response_model=DuplicateCheckResponse)
def check_duplicate_upload(
    *,
    course_name: str,
    lecture_date: date,
    lecture_number: int,
    db: Session = Depends(get_db),
) -> DuplicateCheckResponse:
    """
    講義(講座名・日付・回)の重複有無を事前チェックする。
    既に登録済みなら file_id を返す。
    """
    existing = (
        db.query(models.UploadedFile)
        .filter_by(
            course_name=course_name,
            lecture_date=lecture_date,
            lecture_number=lecture_number,
        )
        .first()
    )
    if not existing:
        return DuplicateCheckResponse(exists=False, file_id=None)
    return DuplicateCheckResponse(exists=True, file_id=existing.file_id)


@router.delete("/uploads/{file_id}", response_model=DeleteUploadResponse)
def delete_uploaded_analysis(
    file_id: int,
    db: Session = Depends(get_db),
) -> DeleteUploadResponse:
    """
    誤ってアップロードした分析対象および結果（関連コメント/調査回答）を削除する。
    進行中(PROCESSING)の場合は競合とする。
    """
    uploaded = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.file_id == file_id)
        .first()
    )
    if not uploaded:
        raise HTTPException(status_code=404, detail=f"File with id {file_id} not found")

    if uploaded.status == "PROCESSING":
        raise HTTPException(status_code=409, detail="File is currently processing")

    removed_comments = (
        db.query(models.Comment)
        .filter(models.Comment.file_id == file_id)
        .delete(synchronize_session=False)
    )
    removed_survey_responses = (
        db.query(models.SurveyResponse)
        .filter(models.SurveyResponse.file_id == file_id)
        .delete(synchronize_session=False)
    )

    # 物理ファイルの削除（可能な場合）
    try:
        if uploaded.s3_key:
            storage_client = get_storage_client()
            storage_client.delete(uri=uploaded.s3_key)
    except Exception:
        # ストレージ削除エラーは致命的ではないためログのみ（ここでは簡略化）
        pass

    db.delete(uploaded)
    db.commit()

    return DeleteUploadResponse(
        file_id=file_id,
        deleted=True,
        removed_comments=removed_comments or 0,
        removed_survey_responses=removed_survey_responses or 0,
    )


@router.post("/uploads/{file_id}/finalize")
def finalize_analysis(
    file_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    速報版(preliminary)のコメントを確定版(final)として固定化する。
    既存のfinalデータがある場合は置き換える。
    """
    uploaded = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.file_id == file_id)
        .first()
    )
    if not uploaded:
        raise HTTPException(status_code=404, detail=f"File with id {file_id} not found")

    # 既存のfinalを削除
    db.query(models.Comment).filter(
        models.Comment.file_id == file_id,
        models.Comment.analysis_version == "final",
    ).delete(synchronize_session=False)

    # preliminaryをコピー
    prelim_comments = (
        db.query(models.Comment)
        .filter(
            models.Comment.file_id == file_id,
            (models.Comment.analysis_version == "preliminary")
            | (models.Comment.analysis_version.is_(None)),
        )
        .all()
    )

    created = 0
    for c in prelim_comments:
        clone = models.Comment(
            file_id=c.file_id,
            survey_response_id=c.survey_response_id,
            account_id=c.account_id,
            account_name=c.account_name,
            question_text=c.question_text,
            comment_text=c.comment_text,
            llm_category=c.llm_category,
            llm_sentiment=c.llm_sentiment,
            llm_summary=c.llm_summary,
            llm_importance_level=c.llm_importance_level,
            llm_importance_score=c.llm_importance_score,
            llm_risk_level=c.llm_risk_level,
            processed_at=c.processed_at,
            analysis_version="final",
        )
        db.add(clone)
        created += 1

    uploaded.finalized_at = datetime.utcnow()
    db.add(uploaded)
    db.commit()

    return {"file_id": file_id, "finalized": True, "final_count": created}



@router.post("/uploads", response_model=UploadResponse)
async def upload_and_enqueue_analysis(
    file: Annotated[UploadFile, File()],
    metadata_json: Annotated[str, Form(alias="metadata")],
    db: Session = Depends(get_db),
) -> UploadResponse:
    """
    CSVを受け取り、基本的な検証とストレージ保存を行った上で、
    LLM分析をバックグラウンドタスクへ委譲します。
    """

    try:
        metadata = metadata_adapter.validate_json(metadata_json)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid metadata format: {exc}"
        )

    try:
        content_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to read uploaded file: {exc}"
        )

    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        validate_csv_or_raise(content_bytes)
    except CsvValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    storage_client = get_storage_client()
    storage_relative_path = build_storage_path(metadata, file.filename)
    try:
        stored_uri = storage_client.save(
            relative_path=storage_relative_path,
            data=content_bytes,
            content_type=file.content_type,
        )
    except StorageError as exc:
        logger.exception("Failed to persist uploaded file.")
        raise HTTPException(
            status_code=500, detail="Failed to persist uploaded file."
        ) from exc

    new_file_record = models.UploadedFile(
        course_name=metadata.course_name,
        lecture_date=metadata.lecture_date,
        lecture_number=metadata.lecture_number,
        lecture_id=metadata.lecture_id,
        status=QUEUED_STATUS,
        s3_key=stored_uri,
        upload_timestamp=datetime.utcnow(),
        original_filename=file.filename,
        content_type=file.content_type,
        total_rows=0,
        processed_rows=0,
    )

    try:
        db.add(new_file_record)
        db.commit()
        db.refresh(new_file_record)
    except IntegrityError:
        db.rollback()
        # 競合した既存のレコードを検索して、より詳細なエラー情報を提供する
        existing_file = (
            db.query(models.UploadedFile)
            .filter_by(
                course_name=metadata.course_name,
                lecture_date=metadata.lecture_date,
                lecture_number=metadata.lecture_number,
            )
            .first()
        )
        detail = "A file for this course, date, and lecture number already exists."
        if existing_file:
            detail += f" The conflicting file_id is {existing_file.file_id}."

        raise HTTPException(status_code=409, detail=detail)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database error on creating file record: {exc}"
        )

    try:
        async_result = process_uploaded_file.delay(file_id=new_file_record.file_id)
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to enqueue background task.")
        db.refresh(new_file_record)
        new_file_record.status = "FAILED"
        new_file_record.error_message = f"Failed to enqueue background task: {exc}"
        db.add(new_file_record)
        db.commit()
        raise HTTPException(
            status_code=500, detail="Failed to enqueue background analysis job."
        ) from exc

    try:
        db.refresh(new_file_record)
    except Exception:
        pass

    if async_result:
        task_id = getattr(async_result, "id", None)
        if task_id and new_file_record.task_id != task_id:
            new_file_record.task_id = task_id
            db.add(new_file_record)
            db.commit()

    return UploadResponse(
        file_id=new_file_record.file_id,
        status_url=f"/api/v1/uploads/{new_file_record.file_id}/status",
        message="Upload accepted. Analysis will run in the background.",
    )
