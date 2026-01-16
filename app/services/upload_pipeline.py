from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Iterable
from uuid import uuid4

import openpyxl
from sqlalchemy.orm import Session

from app.analysis.analyzer import analyze_comment
from app.db import models
from app.schemas.analysis import QuestionType
from app.schemas.comment import UploadRequestMetadata

logger = logging.getLogger(__name__)

# （任意）で始まる列をLLM分析対象とする
LLM_ANALYSIS_TARGET_PREFIX = "（任意）"
# 【必須】または（任意）から始まる列をコメントとして保存
COMMENT_SAVE_TARGET_PREFIXES = ("（任意）", "【必須】")
ACCOUNT_ID_KEYS = ["アカウントID", "account_id", "アカウント ID"]
STUDENT_ATTRIBUTE_KEYS = ["受講生の属性", "受講生属性", "student_attribute"]


class CsvValidationError(ValueError):
    """CSVが検証ルールを満たさない場合に送出される。"""


def analyze_and_store_comments(
    *,
    db: Session,
    survey_batch: models.SurveyBatch,
    content_bytes: bytes,
    filename: str | None = None,
    debug_logging: bool = False,
) -> tuple[int, int, int]:
    """
    CSVを解析しLLM分析と保存を実施する。

    Returns:
        total_comments: 総コメント件数
        processed_comments: LLM処理に成功したコメント件数
        total_responses: アンケート回答行数
    """

    reader, analyzable_columns = _prepare_data_reader(content_bytes, filename=filename)

    total_comments = 0
    processed_comments = 0
    total_responses = 0
    debug_logs_enabled = debug_logging or logger.isEnabledFor(logging.DEBUG)

    # 数値評価カラムとモデル属性の対応表
    score_column_map = {
        "本日の総合的な満足度を５段階で教えてください。": "score_satisfaction_overall",
        "本日の講義内容について５段階で教えてください。\n学習量は適切だった": "score_content_volume",
        "本日の講義内容について５段階で教えてください。\n講義内容が十分に理解できた": "score_content_understanding",
        "本日の講義内容について５段階で教えてください。\n運営側のアナウンスが適切だった": "score_content_announcement",
        "本日の講師の総合的な満足度を５段階で教えてください。": "score_instructor_overall",
        "本日の講師について５段階で教えてください。\n授業時間を効率的に使っていた": "score_instructor_time",
        "本日の講師について５段階で教えてください。\n質問に丁寧に対応してくれた": "score_instructor_qa",
        "本日の講師について５段階で教えてください。\n話し方や声の大きさが適切だった": "score_instructor_speaking",
        "ご自身について５段階で教えてください。\n事前に予習をした": "score_self_preparation",
        "ご自身について５段階で教えてください。\n意欲をもって講義に臨んだ": "score_self_motivation",
        "ご自身について５段階で教えてください。\n今回学んだことを学習や研究に生かせる": "score_self_future",
        "親しいご友人にこの講義の受講をお薦めしますか？": "score_recommend_friend",
    }

    for _, row in enumerate(reader, start=1):
        if debug_logs_enabled:
            logger.debug("--- Processing new CSV row ---")
            logger.debug("Raw row data from CSV: %s", row)

        account_id = _get_value_from_keys(row, ACCOUNT_ID_KEYS, debug_logs_enabled)
        student_attribute = _get_value_from_keys(row, STUDENT_ATTRIBUTE_KEYS, debug_logs_enabled)

        if debug_logs_enabled:
            logger.debug("Extracted account_id: %s", account_id)

        # 数値評価を1行1件でSurveyResponseに保存
        survey_response_data = {
            "survey_batch_id": survey_batch.id,
            "account_id": account_id,
            "student_attribute": student_attribute or "ALL",
        }
        for col_name, attr_name in score_column_map.items():
            if col_name in row and row[col_name] and row[col_name].isdigit():
                survey_response_data[attr_name] = int(row[col_name])

        # score_recommend_friendをそのまま保持

        survey_response_record = models.SurveyResponse(**survey_response_data)
        db.add(survey_response_record)
        # ResponseCommentが参照できるようIDを確定
        db.flush()

        total_responses += 1

        # 自由記述をResponseCommentに保存
        for column_name, comment_text in _extract_comment_texts(row, analyzable_columns):
            # LLM分析対象かを判定
            should_analyze_with_llm = column_name.startswith(LLM_ANALYSIS_TARGET_PREFIX)

            # Map to Enum
            q_type = _map_column_to_question_type(column_name)

            total_comments += 1

            analysis_result = analyze_comment(
                comment_text,
                course_name=survey_batch.lecture.name,
                question_text=column_name,
                # 分析不要な場合はスキップフラグを渡す
                skip_llm_analysis=not should_analyze_with_llm,
            )
            if analysis_result.warnings:
                logger.warning(
                    "LLM warnings for comment: %s",
                    "; ".join(analysis_result.warnings),
                )

            comment_to_add = models.ResponseComment(
                response_id=survey_response_record.id,
                question_type=q_type.value,
                comment_text=comment_text,
                llm_category=analysis_result.category_normalized.value,
                llm_sentiment_type=(
                    analysis_result.sentiment_normalized.value if analysis_result.sentiment_normalized else None
                ),
                llm_priority=(
                    analysis_result.priority_normalized.value if analysis_result.priority_normalized else None
                ),
                llm_fix_difficulty=(
                    analysis_result.fix_difficulty_normalized.value
                    if analysis_result.fix_difficulty_normalized
                    else None
                ),
                llm_is_abusive=analysis_result.is_abusive,
                is_analyzed=True,
            )

            if debug_logs_enabled:
                logger.debug(
                    "Attempting to save Comment object with data: %s",
                    comment_to_add.__dict__,
                )
            db.add(comment_to_add)
            processed_comments += 1

    # survey_batch.total_responses = total_responses
    # survey_batch.total_comments = total_comments
    # db.add(survey_batch)

    return total_comments, processed_comments, total_responses


def validate_csv_or_raise(content_bytes: bytes, filename: str | None = None) -> None:
    """
    Perform header validation. Raises CsvValidationError when invalid.
    """
    _prepare_data_reader(content_bytes, filename=filename, for_validation_only=True)


def build_storage_path(metadata: UploadRequestMetadata, filename: str | None) -> str:
    course = _slugify(metadata.course_name)
    lecture_segment = f"{metadata.lecture_on.isoformat()}-lecture-{metadata.lecture_number}"
    safe_filename = _slugify(filename or "uploaded.csv", allow_period=True)
    return "/".join((course, lecture_segment, f"{uuid4().hex}_{safe_filename}"))


def _prepare_data_reader(
    content_bytes: bytes,
    filename: str | None = None,
    *,
    for_validation_only: bool = False,
):
    """
    Prepare a reader (list of dicts) from CSV or Excel content.
    """
    is_excel = filename and (filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"))

    if is_excel:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content_bytes), data_only=True)
            sheet = wb.active
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                raise CsvValidationError("Uploaded Excel file is empty.")

            header_row = rows[0]
            data_rows = rows[1:]

            # Normalize headers
            normalized_fieldnames = [str(h).strip() if h is not None else "" for h in header_row]

            # Create list of dicts
            reader = []
            for row in data_rows:
                # Pad row with None if shorter than header
                padded_row = list(row) + [None] * (len(normalized_fieldnames) - len(row))
                item = {k: v for k, v in zip(normalized_fieldnames, padded_row, strict=True)}
                reader.append(item)

        except ImportError:
            raise CsvValidationError("openpyxl is required for Excel files.") from None
        except Exception as exc:
            raise CsvValidationError(f"Failed to parse Excel file: {exc}") from exc

    else:
        # CSV handling
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
        csv_reader.fieldnames = normalized_fieldnames
        reader = list(csv_reader)  # Convert to list to unify interface

    if any(not header for header in normalized_fieldnames):
        raise CsvValidationError("Header contains an empty column name.")

    if len(set(normalized_fieldnames)) != len(normalized_fieldnames):
        raise CsvValidationError("Header contains duplicate column names after normalization.")

    analyzable_columns = [name for name in normalized_fieldnames if name.startswith(COMMENT_SAVE_TARGET_PREFIXES)]
    if not analyzable_columns:
        raise CsvValidationError(
            "File must contain at least one column whose header starts with '（任意）' or '【必須】'."
        )

    if for_validation_only:
        return None, analyzable_columns

    return reader, analyzable_columns


def _extract_comment_texts(row: dict, analyzable_columns: Iterable[str]) -> list[tuple[str, str]]:
    comment_texts: list[tuple[str, str]] = []
    for column in analyzable_columns:
        value = _normalize_cell(row.get(column))
        if value:
            comment_texts.append((column, value))
    return comment_texts


def _normalize_cell(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _slugify(raw_value: str, *, allow_period: bool = False) -> str:
    value = raw_value.strip().lower()
    if allow_period:
        pattern = r"[^a-z0-9._-]+"
    else:
        pattern = r"[^a-z0-9_-]+"
    value = re.sub(pattern, "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "value"


def _get_value_from_keys(row_dict: dict, keys: Iterable[str], debug_logs_enabled: bool) -> str | None:
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


def _map_column_to_question_type(column_name: str) -> QuestionType:
    """Map CSV column header to QuestionType enum."""
    # Remove prefixes
    name = column_name
    for prefix in COMMENT_SAVE_TARGET_PREFIXES:
        name = name.replace(prefix, "")
    name = name.strip()

    if "学んだこと" in name or "学び" in name:
        return QuestionType.learned
    if "良かった点" in name or "良い点" in name:
        return QuestionType.good_points
    if "改善点" in name or "改善" in name:
        return QuestionType.improvements
    if "講師" in name and "フィードバック" in name:
        return QuestionType.instructor_feedback
    if "要望" in name:
        return QuestionType.future_requests

    return QuestionType.free_comment
