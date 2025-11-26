from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from celery import Task
from sqlalchemy.orm import Session

from app.db import models
from app.db import session as db_session
from app.services import StorageError, get_storage_client
from app.services.summary import compute_and_upsert_summaries
from app.services.upload_pipeline import CsvValidationError, analyze_and_store_comments

from .celery_app import celery_app

logger = logging.getLogger(__name__)

PROCESSING_STATUS = "PROCESSING"
COMPLETED_STATUS = "COMPLETED"
FAILED_STATUS = "FAILED"


@celery_app.task(
    bind=True,
    name="app.workers.process_uploaded_file",
    max_retries=celery_app.conf.task_max_retries,
    default_retry_delay=celery_app.conf.task_default_retry_delay,
)
def process_uploaded_file(self: Task, *, file_id: int) -> dict:
    """
    Process an uploaded CSV by running LLM analysis for each comment.

    Returns:
        辞書形式の処理統計情報
    """

    session: Session = db_session.SessionLocal()
    storage_client = get_storage_client()
    file_record: Optional[models.UploadedFile] = None
    survey_batch: Optional[models.SurveyBatch] = None

    try:
        file_record = session.get(models.UploadedFile, file_id)
        if not file_record:
            logger.warning("UploadedFile not found for file_id=%s", file_id)
            return {"file_id": file_id, "status": "missing"}

        file_record.status = PROCESSING_STATUS
        file_record.processing_started_at = datetime.now(UTC)
        file_record.error_message = None
        session.add(file_record)
        session.commit()

        content_bytes = storage_client.load(uri=file_record.s3_key)

        # SurveyBatch を作成または取得
        survey_batch = (
            session.query(models.SurveyBatch)
            .filter(models.SurveyBatch.file_id == file_id)
            .first()
        )
        if not survey_batch:
            survey_batch = models.SurveyBatch(
                file_id=file_record.file_id,
                lecture_id=file_record.lecture_id,
                course_name=file_record.course_name,
                lecture_date=file_record.lecture_date,
                lecture_number=file_record.lecture_number,
                academic_year=file_record.academic_year,
                period=file_record.period,
                status=PROCESSING_STATUS,
                upload_timestamp=file_record.upload_timestamp,
                processing_started_at=datetime.now(UTC),
                error_message=None,
            )
            session.add(survey_batch)
            session.flush()
        else:
            survey_batch.status = PROCESSING_STATUS
            survey_batch.processing_started_at = datetime.now(UTC)
            survey_batch.error_message = None
            session.add(survey_batch)

        total_comments, processed_comments, total_responses = analyze_and_store_comments(
            db=session,
            file_record=file_record,
            survey_batch=survey_batch,
            content_bytes=content_bytes,
        )

        # 挿入済みのコメント/回答を先に確定させ、後続の重い集計でのロールバックを避ける
        session.commit()

        now = datetime.now(UTC)
        file_record.status = COMPLETED_STATUS
        file_record.processing_completed_at = now
        file_record.total_rows = total_comments
        file_record.processed_rows = processed_comments
        session.add(file_record)

        survey_batch.status = COMPLETED_STATUS
        survey_batch.processing_completed_at = now
        session.add(survey_batch)

        # Pre-compute summaries for dashboard
        compute_and_upsert_summaries(
            session, survey_batch=survey_batch, version="preliminary"
        )

        session.commit()

        logger.info(
            "Completed analysis for file_id=%s (processed=%s)",
            file_id,
            processed_comments,
        )

        return {
            "file_id": file_id,
            "batch_id": survey_batch.id,
            "status": COMPLETED_STATUS,
            "total_comments": total_comments,
            "processed_comments": processed_comments,
            "total_responses": total_responses,
        }

    except CsvValidationError as exc:
        session.rollback()
        logger.exception("Background processing failed for file_id=%s", file_id)
        _mark_failure(session, file_record, survey_batch=survey_batch, error_message=str(exc))
        raise
    except StorageError as exc:
        session.rollback()
        retries = self.request.retries
        max_retries = (
            self.max_retries
            if self.max_retries is not None
            else self.app.conf.task_max_retries
        )
        logger.warning(
            "StorageError on processing file_id=%s (attempt %s/%s): %s",
            file_id,
            retries + 1,
            max_retries,
            exc,
        )
        if max_retries is not None and retries >= max_retries:
            _mark_failure(session, file_record, survey_batch=survey_batch, error_message=str(exc))
            raise
        raise self.retry(exc=exc)
    except Exception as exc:  # pragma: no cover - unexpected failures
        session.rollback()
        logger.exception("Unexpected failure during background processing.")
        _mark_failure(session, file_record, survey_batch=survey_batch, error_message=str(exc))
        raise
    finally:
        session.close()


def _mark_failure(
    session: Session,
    file_record: Optional[models.UploadedFile],
    *,
    error_message: str,
    survey_batch: Optional[models.SurveyBatch] = None,
) -> None:
    if not file_record:
        return

    truncated = error_message[:1024]
    file_record.status = FAILED_STATUS
    file_record.processing_completed_at = datetime.now(UTC)
    file_record.error_message = truncated
    session.add(file_record)
    if survey_batch:
        survey_batch.status = FAILED_STATUS
        survey_batch.processing_completed_at = datetime.now(UTC)
        survey_batch.error_message = truncated
        session.add(survey_batch)
    try:
        session.commit()
    except Exception:  # pragma: no cover - best-effort logging
        session.rollback()
        logger.error("Failed to persist failure status for file_id=%s", file_record.file_id)
