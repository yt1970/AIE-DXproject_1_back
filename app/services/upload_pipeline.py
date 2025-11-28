from __future__ import annotations

import csv
import io
import logging
import re
from datetime import UTC, datetime
from typing import Iterable, List
from uuid import uuid4

from sqlalchemy.orm import Session

from app.analysis.analyzer import analyze_comment
from app.db import models
from app.schemas.comment import UploadRequestMetadata

logger = logging.getLogger(__name__)

# （任意）で始まる列をLLM分析対象とする
LLM_ANALYSIS_TARGET_PREFIX = "（任意）"
# 【必須】または（任意）から始まる列をコメントとして保存
COMMENT_SAVE_TARGET_PREFIXES = ("（任意）", "【必須】")
ACCOUNT_ID_KEYS = ["アカウントID", "account_id", "アカウント ID"]
ACCOUNT_NAME_KEYS = ["アカウント名", "account_name", "アカウント 名"]
STUDENT_ATTRIBUTE_KEYS = ["受講生の属性", "受講生属性", "student_attribute"]


class CsvValidationError(ValueError):
    """CSVが検証ルールを満たさない場合に送出される。"""


def analyze_and_store_comments(
    *,
    db: Session,
    file_record: models.UploadedFile,
    survey_batch: models.SurveyBatch,
    content_bytes: bytes,
    debug_logging: bool = False,
) -> tuple[int, int, int]:
    """
    CSVを解析しLLM分析と保存を実施する。

    Returns:
        total_comments: 総コメント件数
        processed_comments: LLM処理に成功したコメント件数
        total_responses: アンケート回答行数
    """

    csv_reader, analyzable_columns = _prepare_csv_reader(content_bytes)

    total_comments = 0
    processed_comments = 0
    total_responses = 0
    debug_logs_enabled = debug_logging or logger.isEnabledFor(logging.DEBUG)

    # 数値評価カラムとモデル属性の対応表
    score_column_map = {
        "本日の総合的な満足度を５段階で教えてください。": "score_satisfaction_overall",
        "本日の講義内容について５段階で教えてください。\n学習量は適切だった": "score_satisfaction_content_volume",
        "本日の講義内容について５段階で教えてください。\n講義内容が十分に理解できた": "score_satisfaction_content_understanding",
        "本日の講義内容について５段階で教えてください。\n運営側のアナウンスが適切だった": "score_satisfaction_content_announcement",
        "本日の講師の総合的な満足度を５段階で教えてください。": "score_satisfaction_instructor_overall",
        "本日の講師について５段階で教えてください。\n授業時間を効率的に使っていた": "score_satisfaction_instructor_efficiency",
        "本日の講師について５段階で教えてください。\n質問に丁寧に対応してくれた": "score_satisfaction_instructor_response",
        "本日の講師について５段階で教えてください。\n話し方や声の大きさが適切だった": "score_satisfaction_instructor_clarity",
        "ご自身について５段階で教えてください。\n事前に予習をした": "score_self_preparation",
        "ご自身について５段階で教えてください。\n意欲をもって講義に臨んだ": "score_self_motivation",
        "ご自身について５段階で教えてください。\n今回学んだことを学習や研究に生かせる": "score_self_applicability",
        "親しいご友人にこの講義の受講をお薦めしますか？": "score_recommend_friend",
    }

    for row_index, row in enumerate(csv_reader, start=1):
        if debug_logs_enabled:
            logger.debug("--- Processing new CSV row ---")
            logger.debug("Raw row data from CSV: %s", row)

        account_id = _get_value_from_keys(row, ACCOUNT_ID_KEYS, debug_logs_enabled)
        account_name = _get_value_from_keys(row, ACCOUNT_NAME_KEYS, debug_logs_enabled)
        student_attribute = _get_value_from_keys(
            row, STUDENT_ATTRIBUTE_KEYS, debug_logs_enabled
        )

        if debug_logs_enabled:
            logger.debug(
                "Extracted account_id: %s, account_name: %s", account_id, account_name
            )

        # 数値評価を1行1件でSurveyResponseに保存
        survey_response_data = {
            "uploaded_file_id": file_record.id,
            "survey_batch_id": survey_batch.id,
            "account_id": account_id,
            "account_name": account_name,
            "student_attribute": student_attribute or "ALL",
            "row_index": row_index,
        }
        for col_name, attr_name in score_column_map.items():
            if col_name in row and row[col_name] and row[col_name].isdigit():
                survey_response_data[attr_name] = int(row[col_name])

        # 既存のカラム名に加え、新設計の別名にも値をコピーする
        # instructor効率 -> time, response -> qa, clarity -> speaking
        if "score_satisfaction_instructor_efficiency" in survey_response_data:
            survey_response_data.setdefault(
                "score_instructor_time",
                survey_response_data["score_satisfaction_instructor_efficiency"],
            )
        if "score_satisfaction_instructor_response" in survey_response_data:
            survey_response_data.setdefault(
                "score_instructor_qa",
                survey_response_data["score_satisfaction_instructor_response"],
            )
        if "score_satisfaction_instructor_clarity" in survey_response_data:
            survey_response_data.setdefault(
                "score_instructor_speaking",
                survey_response_data["score_satisfaction_instructor_clarity"],
            )
        if "score_self_applicability" in survey_response_data:
            survey_response_data.setdefault(
                "score_self_future", survey_response_data["score_self_applicability"]
            )
        # score_recommend_friendをそのまま保持

        survey_response_record = models.SurveyResponse(**survey_response_data)
        db.add(survey_response_record)
        # ResponseCommentが参照できるようIDを確定
        db.flush()

        total_responses += 1

        # 自由記述をResponseCommentに保存
        for column_name, comment_text in _extract_comment_texts(
            row, analyzable_columns
        ):
            # LLM分析対象かを判定
            should_analyze_with_llm = column_name.startswith(LLM_ANALYSIS_TARGET_PREFIX)

            total_comments += 1

            analysis_result = analyze_comment(
                comment_text,
                course_name=file_record.course_name,
                question_text=column_name,
                # 分析不要な場合はスキップフラグを渡す
                skip_llm_analysis=not should_analyze_with_llm,
            )
            if analysis_result.warnings:
                logger.warning(
                    "LLM warnings for comment: %s",
                    "; ".join(analysis_result.warnings),
                )

            is_important = (
                1
                if analysis_result.importance_normalized.value in ("medium", "high")
                else 0
            )

            comment_to_add = models.ResponseComment(
                survey_response_id=survey_response_record.id,
                uploaded_file_id=file_record.id,
                survey_batch_id=survey_batch.id,
                account_id=account_id,
                account_name=account_name,
                question_text=column_name,
                question_type=column_name,
                comment_text=comment_text,
                llm_category=analysis_result.category_normalized.value,
                llm_sentiment=(
                    analysis_result.sentiment_normalized.value
                    if analysis_result.sentiment_normalized
                    else None
                ),
                llm_summary=analysis_result.summary,
                llm_importance_level=analysis_result.importance_normalized.value,
                llm_importance_score=analysis_result.importance_score,
                llm_risk_level=analysis_result.risk_level_normalized.value,
                llm_is_abusive=analysis_result.risk_level_normalized
                == models.RiskLevelType.flag,
                processed_at=datetime.now(UTC),
                analysis_version="preliminary",
                is_important=is_important,
                is_analyzed=True,
            )

            if debug_logs_enabled:
                logger.debug(
                    "Attempting to save Comment object with data: %s",
                    comment_to_add.__dict__,
                )
            db.add(comment_to_add)
            processed_comments += 1

    survey_batch.total_responses = total_responses
    survey_batch.total_comments = total_comments
    db.add(survey_batch)

    return total_comments, processed_comments, total_responses


def validate_csv_or_raise(content_bytes: bytes) -> None:
    """
    Perform CSV header validation. Raises CsvValidationError when invalid.
    """
    _prepare_csv_reader(content_bytes, for_validation_only=True)


def build_storage_path(metadata: UploadRequestMetadata, filename: str | None) -> str:
    course = _slugify(metadata.course_name)
    lecture_segment = (
        f"{metadata.lecture_date.isoformat()}-lecture-{metadata.lecture_number}"
    )
    safe_filename = _slugify(filename or "uploaded.csv", allow_period=True)
    return "/".join((course, lecture_segment, f"{uuid4().hex}_{safe_filename}"))


def _prepare_csv_reader(content_bytes: bytes, *, for_validation_only: bool = False):
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
        name
        for name in normalized_fieldnames
        if name.startswith(COMMENT_SAVE_TARGET_PREFIXES)
    ]
    if not analyzable_columns:
        raise CsvValidationError(
            "CSV must contain at least one column whose header starts with '（任意）' or '【必須】'."
        )

    csv_reader.fieldnames = normalized_fieldnames

    if for_validation_only:
        return None, analyzable_columns

    return csv_reader, analyzable_columns


def _extract_comment_texts(
    row: dict, analyzable_columns: Iterable[str]
) -> List[tuple[str, str]]:
    comment_texts: List[tuple[str, str]] = []
    for column in analyzable_columns:
        value = _normalize_cell(row.get(column))
        if value:
            comment_texts.append((column, value))
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


def _get_value_from_keys(
    row_dict: dict, keys: Iterable[str], debug_logs_enabled: bool
) -> str | None:
    if debug_logs_enabled:
        logger.debug("--- Attempting to extract one of keys: %s", keys)
    for key in keys:
        if key in row_dict:
            if debug_logs_enabled:
                logger.debug("  => Found '%s': '%s'", key, row_dict[key])
            return row_dict[key]
        if debug_logs_enabled:
            logger.debug("  - Missing key: '%s'", key)
    if debug_logs_enabled:
        logger.debug("  - None of the candidate keys found in the row.")
    return None
