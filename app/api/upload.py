# app/api/upload.py

import json
import logging
from datetime import UTC, date, datetime
from typing import Annotated, Optional

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


def _derive_academic_year(d: date) -> int:
    # 4月始まりと仮定
    if d.month >= 4:
        return d.year
    return d.year - 1


@router.get("/uploads/check-duplicate", response_model=DuplicateCheckResponse)
def check_duplicate_upload(
    *,
    course_name: str,
    lecture_on: date,
    lecture_number: int,
    db: Session = Depends(get_db),
) -> DuplicateCheckResponse:
    """
    講義(講座名・日付・回)の重複有無を事前チェックする。
    既に登録済みなら survey_batch_id を返す。
    """
    # Lectureを探す
    lecture = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.name == course_name,
            models.Lecture.lecture_on == lecture_on,
            models.Lecture.session == str(lecture_number),
        )
        .first()
    )

    if not lecture:
        return DuplicateCheckResponse(exists=False, survey_batch_id=None)

    # SurveyBatchを探す
    existing_batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.lecture_id == lecture.id)
        .first()
    )

    if not existing_batch:
        return DuplicateCheckResponse(exists=False, survey_batch_id=None)
    
    return DuplicateCheckResponse(exists=True, survey_batch_id=existing_batch.id)


@router.delete("/uploads/{survey_batch_id}", response_model=DeleteUploadResponse)
def delete_uploaded_analysis(
    survey_batch_id: int,
    db: Session = Depends(get_db),
) -> DeleteUploadResponse:
    """
    誤ってアップロードした分析対象および結果（関連コメント/調査回答）を削除する。
    進行中(PROCESSING)の場合は競合とする。
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

    # ステータス判定: SurveySummaryが存在しなければ処理中とみなす
    has_summary = (
        db.query(models.SurveySummary)
        .filter(models.SurveySummary.survey_batch_id == survey_batch.id)
        .first()
    )
    if not has_summary:
        raise HTTPException(status_code=409, detail="Batch is currently processing")

    removed_comments = (
        db.query(models.ResponseComment)
        .filter(models.ResponseComment.response_id.in_(
            db.query(models.SurveyResponse.id).filter(models.SurveyResponse.survey_batch_id == survey_batch_id)
        ))
        .delete(synchronize_session=False)
    )
    removed_survey_responses = (
        db.query(models.SurveyResponse)
        .filter(models.SurveyResponse.survey_batch_id == survey_batch_id)
        .delete(synchronize_session=False)
    )
    
    db.query(models.SurveySummary).filter(
        models.SurveySummary.survey_batch_id == survey_batch.id
    ).delete(synchronize_session=False)
    db.query(models.CommentSummary).filter(
        models.CommentSummary.survey_batch_id == survey_batch.id
    ).delete(synchronize_session=False)
    
    db.delete(survey_batch)
    db.commit()

    return DeleteUploadResponse(
        survey_batch_id=survey_batch_id,
        deleted=True,
        removed_comments=removed_comments or 0,
        removed_survey_responses=removed_survey_responses or 0,
    )


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
    survey_batch.batch_type = 'confirmed'
    # survey_batch.finalized_at = datetime.now(UTC) # モデルにないのでコメントアウト
    
    # 集計の再計算などが必要ならここで実施
    # compute_and_upsert_summaries(db, survey_batch=survey_batch, version="final")
    
    db.add(survey_batch)
    db.commit()

    return {
        "survey_batch_id": survey_batch_id,
        "finalized": True,
    }


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

    # ストレージ保存 (S3など) - 必須ではないがバックアップとして残す想定
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

    # Lectureの特定または作成
    lecture = None
    if metadata.lecture_id:
        lecture = db.query(models.Lecture).filter(models.Lecture.id == metadata.lecture_id).first()
    
    if not lecture:
        # 既存の講義を検索
        lecture = (
            db.query(models.Lecture)
            .filter(
                models.Lecture.name == metadata.course_name,
                models.Lecture.lecture_on == metadata.lecture_on,
                models.Lecture.session == str(metadata.lecture_number),
            )
            .first()
        )
    
    if not lecture:
        # 新規作成
        academic_year = _derive_academic_year(metadata.lecture_on)
        lecture = models.Lecture(
            academic_year=academic_year,
            term="Unknown", # 必須だが不明
            name=metadata.course_name,
            session=str(metadata.lecture_number),
            lecture_on=metadata.lecture_on,
            instructor_name="TBD", # 必須だが不明
            description="Auto-created from upload",
        )
        try:
            db.add(lecture)
            db.commit()
            db.refresh(lecture)
        except IntegrityError:
            db.rollback()
            # 競合した場合は再取得を試みる
            lecture = (
                db.query(models.Lecture)
                .filter(
                    models.Lecture.name == metadata.course_name,
                    models.Lecture.lecture_on == metadata.lecture_on,
                    models.Lecture.session == str(metadata.lecture_number),
                )
                .first()
            )
            if not lecture:
                raise HTTPException(status_code=500, detail="Failed to create or retrieve lecture.")

    # SurveyBatchの作成
    new_batch = models.SurveyBatch(
        lecture_id=lecture.id,
        batch_type='preliminary',
        uploaded_at=datetime.now(UTC),
        # zoom_participants, recording_views は後で更新される想定
    )

    try:
        db.add(new_batch)
        db.commit()
        db.refresh(new_batch)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database error on creating survey batch: {exc}"
        )

    try:
        # 非同期実行（Redisキュー経由）
        # ファイルパスも渡す必要があるが、DBには保存しないため引数で渡すか、
        # あるいはS3キーを一時的に渡す必要がある。
        # ここではS3キーを渡して、Worker側でダウンロードする想定とする。
        process_uploaded_file.delay(batch_id=new_batch.id, s3_key=stored_uri)
    except Exception as exc:
        # 失敗時はレコード削除
        db.delete(new_batch)
        db.commit()
        raise HTTPException(
            status_code=500, detail="Failed to run background analysis job."
        ) from exc

    return UploadResponse(
        survey_batch_id=new_batch.id,
        status_url=f"/api/v1/uploads/{new_batch.id}/status",
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
    
    # Lectureを探す
    q_lecture = db.query(models.Lecture).filter(
        models.Lecture.name == payload.course_name,
        models.Lecture.session == str(payload.lecture_number),
    )
    if payload.academic_year:
        q_lecture = q_lecture.filter(models.Lecture.academic_year == int(payload.academic_year))
    if payload.period:
        q_lecture = q_lecture.filter(models.Lecture.term == payload.period)
        
    lecture = q_lecture.first()
    
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    survey_batch = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.lecture_id == lecture.id)
        .first()
    )

    if not survey_batch:
        raise HTTPException(status_code=404, detail="Survey batch not found")

    # ステータス判定: SurveySummaryが存在しなければ処理中とみなす
    has_summary = (
        db.query(models.SurveySummary)
        .filter(models.SurveySummary.survey_batch_id == survey_batch.id)
        .first()
    )
    if not has_summary:
        raise HTTPException(status_code=409, detail="Batch is currently processing")

    removed_comments = 0
    removed_survey_responses = 0

    # 指定されている場合は、analysis_versionでフィルタリングしてコメントを削除
    # 注: 新設計ではResponseCommentにanalysis_versionがある
    q_comments = db.query(models.ResponseComment).filter(
        models.ResponseComment.response_id.in_(
            db.query(models.SurveyResponse.id).filter(models.SurveyResponse.survey_batch_id == survey_batch.id)
        )
    )
    if payload.analysis_version in {"final", "preliminary"}:
        q_comments = q_comments.filter(
            models.ResponseComment.analysis_version == payload.analysis_version
        )
    removed_comments = q_comments.delete(synchronize_session=False) or 0

    # バージョン指定なしなら関連データも削除
    if payload.analysis_version is None:
        removed_survey_responses = (
            db.query(models.SurveyResponse)
            .filter(models.SurveyResponse.survey_batch_id == survey_batch.id)
            .delete(synchronize_session=False)
            or 0
        )
        
        db.query(models.SurveySummary).filter(
            models.SurveySummary.survey_batch_id == survey_batch.id
        ).delete(synchronize_session=False)
        db.query(models.CommentSummary).filter(
            models.CommentSummary.survey_batch_id == survey_batch.id
        ).delete(synchronize_session=False)
        
        db.delete(survey_batch)
    else:
        # 特定バージョンのみ削除した場合は該当サマリのみ削除
        # SurveySummaryにはanalysis_versionがある
        if payload.analysis_version in {"final", "preliminary"}:
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
        survey_batch_id=survey_batch.id,
        deleted=True,
        removed_comments=removed_comments,
        removed_survey_responses=removed_survey_responses,
    )
