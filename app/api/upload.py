# app/api/upload.py

import json
import logging
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, TypeAdapter, ValidationError
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
    # バッチ・サマリも削除
    survey_batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.file_id == file_id)
        .first()
    )
    if survey_batch:
        db.query(models.SurveySummary).filter(
            models.SurveySummary.survey_batch_id == survey_batch.id
        ).delete(synchronize_session=False)
        db.query(models.CommentSummary).filter(
            models.CommentSummary.survey_batch_id == survey_batch.id
        ).delete(synchronize_session=False)
        db.delete(survey_batch)

    # 可能な場合物理ファイルの削除
    try:
        if uploaded.s3_key:
            storage_client = get_storage_client()
            storage_client.delete(uri=uploaded.s3_key)
    except Exception:
        # ストレージ削除エラーは致命的ではないためログのみ
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

    survey_batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.file_id == file_id)
        .first()
    )
    if not survey_batch:
        # processingなしでfinalizeが呼ばれた場合に備えて作成
        survey_batch = models.SurveyBatch(
            file_id=uploaded.file_id,
            lecture_id=uploaded.lecture_id,
            course_name=uploaded.course_name,
            lecture_date=uploaded.lecture_date,
            lecture_number=uploaded.lecture_number,
            academic_year=uploaded.academic_year,
            period=uploaded.period,
            status=uploaded.status,
            upload_timestamp=uploaded.upload_timestamp,
            processing_started_at=uploaded.processing_started_at,
            processing_completed_at=uploaded.processing_completed_at,
            total_responses=uploaded.processed_rows,
            total_comments=uploaded.total_rows,
        )
        db.add(survey_batch)
        db.flush()

    # 既存のfinalを削除
    db.query(models.Comment).filter(
        models.Comment.file_id == file_id,
        models.Comment.analysis_version == "final",
    ).delete(synchronize_session=False)

    # bulk insertで負荷を抑制のためpreliminaryをコピー
    prelim_rows = (
        db.query(
            models.Comment.file_id,
            models.Comment.survey_response_id,
            models.Comment.survey_batch_id,
            models.Comment.account_id,
            models.Comment.account_name,
            models.Comment.question_text,
            models.Comment.comment_text,
            models.Comment.llm_category,
            models.Comment.llm_sentiment,
            models.Comment.llm_summary,
            models.Comment.llm_importance_level,
            models.Comment.llm_importance_score,
            models.Comment.llm_risk_level,
            models.Comment.processed_at,
            models.Comment.is_important,
        )
        .filter(
            models.Comment.file_id == file_id,
            (models.Comment.analysis_version == "preliminary")
            | (models.Comment.analysis_version.is_(None)),
        )
        .all()
    )

    payloads = [
        {
            "file_id": row.file_id,
            "survey_response_id": row.survey_response_id,
            "survey_batch_id": row.survey_batch_id or survey_batch.id,
            "account_id": row.account_id,
            "account_name": row.account_name,
            "question_text": row.question_text,
            "comment_text": row.comment_text,
            "llm_category": row.llm_category,
            "llm_sentiment": row.llm_sentiment,
            "llm_summary": row.llm_summary,
            "llm_importance_level": row.llm_importance_level,
            "llm_importance_score": row.llm_importance_score,
            "llm_risk_level": row.llm_risk_level,
            "processed_at": row.processed_at,
            "analysis_version": "final",
            "is_important": row.is_important,
        }
        for row in prelim_rows
    ]
    created = len(payloads)
    if payloads:
        db.bulk_insert_mappings(models.Comment, payloads)

    now = datetime.now(UTC)
    uploaded.finalized_at = now
    survey_batch.finalized_at = now
    db.add(uploaded)
    db.add(survey_batch)
    compute_and_upsert_summaries(db, survey_batch=survey_batch, version="final")
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
        raise HTTPException(status_code=422, detail=f"Invalid metadata format: {exc}")

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
        upload_timestamp=datetime.now(UTC),
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
    except Exception as exc:
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


class UploadIdentityDeleteRequest(BaseModel):
    """削除するアップロードデータセットを選択するための識別情報"""

    course_name: str
    academic_year: str | None = None
    period: str | None = None
    lecture_number: int
    analysis_version: str | None = None


@router.delete("/uploads/by-identity", response_model=DeleteUploadResponse)
def delete_uploaded_by_identity(
    payload: UploadIdentityDeleteRequest, db: Session = Depends(get_db)
) -> DeleteUploadResponse:
    """講義の識別情報とバージョンフィルタを使用して、単一のアップロードデータセットを削除する"""
    uploaded = (
        db.query(models.UploadedFile)
        .filter(
            models.UploadedFile.course_name == payload.course_name,
            models.UploadedFile.lecture_number == payload.lecture_number,
        )
        .first()
    )
    # 提供されている場合は、academic_year/periodで絞り込む
    if uploaded and payload.academic_year:
        if uploaded.academic_year != str(payload.academic_year):
            uploaded = None
    if uploaded and payload.period:
        if (uploaded.period or "").lower() != payload.period.lower():
            uploaded = None

    if not uploaded:
        raise HTTPException(status_code=404, detail="Uploaded dataset not found")

    if uploaded.status == "PROCESSING":
        raise HTTPException(status_code=409, detail="File is currently processing")

    removed_comments = 0
    removed_survey_responses = 0

    # 指定されている場合は、analysis_versionでフィルタリングしてコメントを削除
    q_comments = db.query(models.Comment).filter(
        models.Comment.file_id == uploaded.file_id
    )
    if payload.analysis_version in {"final", "preliminary"}:
        q_comments = q_comments.filter(
            models.Comment.analysis_version == payload.analysis_version
        )
    removed_comments = q_comments.delete(synchronize_session=False) or 0

    # バージョン指定の削除でコメントのみが削除された場合はファイルを保持、それ以外はsurvey/metrics/fileも削除
    # versionがNoneの場合は、データセット全体を削除する
    if payload.analysis_version is None:
        removed_survey_responses = (
            db.query(models.SurveyResponse)
            .filter(models.SurveyResponse.file_id == uploaded.file_id)
            .delete(synchronize_session=False)
            or 0
        )
        survey_batch = (
            db.query(models.SurveyBatch)
            .filter(models.SurveyBatch.file_id == uploaded.file_id)
            .first()
        )
        if survey_batch:
            db.query(models.SurveySummary).filter(
                models.SurveySummary.survey_batch_id == survey_batch.id
            ).delete(synchronize_session=False)
            db.query(models.CommentSummary).filter(
                models.CommentSummary.survey_batch_id == survey_batch.id
            ).delete(synchronize_session=False)
            db.delete(survey_batch)
        db.query(models.LectureMetrics).filter(
            models.LectureMetrics.file_id == uploaded.file_id
        ).delete(synchronize_session=False)
        # ベストエフォートでストレージからも削除
        try:
            if uploaded.s3_key:
                storage_client = get_storage_client()
                storage_client.delete(uri=uploaded.s3_key)
        except Exception:
            pass
        db.delete(uploaded)
    else:
        # 特定バージョンのみ削除した場合は該当サマリのみ削除
        survey_batch = (
            db.query(models.SurveyBatch)
            .filter(models.SurveyBatch.file_id == uploaded.file_id)
            .first()
        )
        if survey_batch and payload.analysis_version in {"final", "preliminary"}:
            db.query(models.SurveySummary).filter(
                models.SurveySummary.survey_batch_id == survey_batch.id,
                models.SurveySummary.analysis_version == payload.analysis_version,
            ).delete(synchronize_session=False)
            db.query(models.CommentSummary).filter(
                models.CommentSummary.survey_batch_id == survey_batch.id,
                models.CommentSummary.analysis_version == payload.analysis_version,
            ).delete(synchronize_session=False)

    db.commit()
    return DeleteUploadResponse(
        file_id=uploaded.file_id,
        deleted=True,
        removed_comments=removed_comments,
        removed_survey_responses=removed_survey_responses,
    )
