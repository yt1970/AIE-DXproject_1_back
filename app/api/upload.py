# app/api/upload.py

import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db import models
from app.db.session import get_db
from app.schemas.comment import UploadRequestMetadata, UploadResponse
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
