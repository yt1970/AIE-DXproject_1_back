from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Iterable, List
from uuid import uuid4

from sqlalchemy.orm import Session

from app.analysis.analyzer import analyze_comment
from app.db import models
from app.schemas.comment import UploadRequestMetadata

logger = logging.getLogger(__name__)

COMMENT_ANALYSIS_PREFIX = "（任意）"


class CsvValidationError(ValueError):
    """Raised when the uploaded CSV does not satisfy validation rules."""


def analyze_and_store_comments(
    *,
    db: Session,
    file_record: models.UploadedFile,
    content_bytes: bytes,
) -> tuple[int, int]:
    """
    Parse the uploaded CSV, run LLM analysis for each comment, and persist the results.

    Returns:
        total_comments: 総コメント件数
        processed_comments: LLM処理に成功したコメント件数
    """

    csv_reader, analyzable_columns = _prepare_csv_reader(content_bytes)

    total_comments = 0
    processed_comments = 0

    for row in csv_reader:
        for comment_text in _extract_comment_texts(row, analyzable_columns):
            total_comments += 1

            analysis_result = analyze_comment(comment_text)
            if analysis_result.warnings:
                logger.warning(
                    "LLM warnings for comment: %s",
                    "; ".join(analysis_result.warnings),
                )

            processed_comments += 1
            db.add(
                models.Comment(
                    file_id=file_record.file_id,
                    comment_text=comment_text,
                    llm_category=analysis_result.category,
                    llm_sentiment=analysis_result.sentiment,
                    llm_summary=analysis_result.summary,
                    llm_importance_level=analysis_result.importance_level,
                    llm_importance_score=analysis_result.importance_score,
                    llm_risk_level=analysis_result.risk_level,
                    processed_at=datetime.utcnow(),
                )
            )

    file_record.total_rows = total_comments
    file_record.processed_rows = processed_comments

    return total_comments, processed_comments


def validate_csv_or_raise(content_bytes: bytes) -> None:
    """
    Perform CSV header validation. Raises CsvValidationError when invalid.
    """
    _prepare_csv_reader(content_bytes, for_validation_only=True)


def build_storage_path(
    metadata: UploadRequestMetadata, filename: str | None
) -> str:
    course = _slugify(metadata.course_name)
    lecture_segment = (
        f"{metadata.lecture_date.isoformat()}-lecture-{metadata.lecture_number}"
    )
    safe_filename = _slugify(filename or "uploaded.csv", allow_period=True)
    return "/".join(
        (course, lecture_segment, f"{uuid4().hex}_{safe_filename}")
    )


def _prepare_csv_reader(
    content_bytes: bytes, *, for_validation_only: bool = False
):
    try:
        content_text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvValidationError(f"CSV must be UTF-8 encoded: {exc}") from exc

    if not content_text:
        raise CsvValidationError("Uploaded file is empty.")

    csv_stream = io.StringIO(content_text)
    csv_reader = csv.DictReader(csv_stream)

    if not csv_reader.fieldnames:
        raise CsvValidationError("CSV header row is missing.")

    normalized_fieldnames = [header.strip() for header in csv_reader.fieldnames]

    if any(not header for header in normalized_fieldnames):
        raise CsvValidationError("CSV header contains an empty column name.")

    if len(set(normalized_fieldnames)) != len(normalized_fieldnames):
        raise CsvValidationError(
            "CSV header contains duplicate column names after normalization."
        )

    analyzable_columns = [
        name for name in normalized_fieldnames if name.startswith(COMMENT_ANALYSIS_PREFIX)
    ]
    if not analyzable_columns:
        raise CsvValidationError(
            "CSV must contain at least one column whose header starts with '（任意）'."
        )

    csv_reader.fieldnames = normalized_fieldnames

    if for_validation_only:
        return None, analyzable_columns

    return csv_reader, analyzable_columns


def _extract_comment_texts(
    row: dict, analyzable_columns: Iterable[str]
) -> List[str]:
    comment_texts: List[str] = []
    for column in analyzable_columns:
        value = _normalize_cell(row.get(column))
        if value:
            comment_texts.append(value)
    return comment_texts


def _normalize_cell(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _slugify(raw_value: str, *, allow_period: bool = False) -> str:
    value = raw_value.strip().lower()
    if allow_period:
        pattern = r"[^a-z0-9._-]+"
    else:
        pattern = r"[^a-z0-9_-]+"
    value = re.sub(pattern, "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "value"
