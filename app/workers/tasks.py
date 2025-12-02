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

COMPLETED_STATUS = "COMPLETED"


@celery_app.task(
    bind=True,
    name="app.workers.process_uploaded_file",
    max_retries=celery_app.conf.task_max_retries,
    default_retry_delay=celery_app.conf.task_default_retry_delay,
)
def process_uploaded_file(self: Task, *, batch_id: int, s3_key: str) -> dict:
    """
    Process an uploaded CSV by running LLM analysis for each comment.
    
    Args:
        batch_id: SurveyBatch ID
        s3_key: S3 key (or path) to download the file from
    """

    session: Session = db_session.SessionLocal()
    storage_client = get_storage_client()
    survey_batch: Optional[models.SurveyBatch] = None

    try:
        survey_batch = session.get(models.SurveyBatch, batch_id)
        if not survey_batch:
            logger.warning("SurveyBatch not found for batch_id=%s", batch_id)
            return {"batch_id": batch_id, "status": "missing"}

        # Note: Status tracking columns (status, processing_started_at, etc.) 
        # have been removed from the design, so we don't update them here.
        
        content_bytes = storage_client.load(uri=s3_key)

        total_comments, processed_comments, total_responses = (
            analyze_and_store_comments(
                db=session,
                survey_batch=survey_batch,
                content_bytes=content_bytes,
                filename=s3_key,
            )
        )

        # 挿入済みのコメント/回答を先に確定させ、後続の重い集計でのロールバックを避ける
        session.commit()

        # Pre-compute summaries for dashboard
        # This effectively marks the batch as "done" when summaries are present
        compute_and_upsert_summaries(
            session, survey_batch=survey_batch, version="preliminary"
        )

        session.commit()

        logger.info(
            "Completed analysis for batch_id=%s (processed=%s)",
            batch_id,
            processed_comments,
        )

        return {
            "batch_id": batch_id,
            "status": "COMPLETED",
            "total_comments": total_comments,
            "processed_comments": processed_comments,
            "total_responses": total_responses,
        }

    except CsvValidationError as exc:
        session.rollback()
        logger.exception("Background processing failed for batch_id=%s", batch_id)
        # Cannot store error message in DB as per design
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
            "StorageError on processing batch_id=%s (attempt %s/%s): %s",
            batch_id,
            retries + 1,
            max_retries,
            exc,
        )
        if max_retries is not None and retries >= max_retries:
            raise
        raise self.retry(exc=exc)
    except Exception as exc:  # pragma: no cover - unexpected failures
        session.rollback()
        logger.exception("Unexpected failure during background processing.")
        raise
    finally:
        session.close()
