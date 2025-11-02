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

# （任意）で始まる列のみをLLM分析の対象とする
LLM_ANALYSIS_TARGET_PREFIX = "（任意）"
# 【必須】または（任意）で始まる列をコメントとしてDBに保存する
COMMENT_SAVE_TARGET_PREFIXES = ("（任意）", "【必須】")


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

    # 数値評価カラムとDBモデル属性のマッピング
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
        "親しいご友人にこの講義の受講をお薦めしますか？": "score_recommend_to_friend",
    }

    for row in csv_reader:
        # ★★★ デバッグログポイント 1: CSVの1行を読み込んだ直後の生データを表示 ★★★
        # これで、CSVのヘッダー名が正しく認識されているか、値が空でないかを確認します。
        logger.info("--- Processing new CSV row ---")
        logger.info("Raw row data from CSV: %s", row)

        # ★★★ 修正点 ★★★
        # 本番用の日本語ヘッダー名と、開発用の英語キー名の両方に対応する。
        # ヘッダー名の揺れ（間の空白など）を吸収するため、複数の候補キーで検索し、その過程をログに出力する。
        def get_value_from_keys(row_dict, keys):
            for key in keys:
                logger.info("  - Checking for key: '%s'", key)
                if key in row_dict:
                    logger.info("    => Found! Value: '%s'", row_dict[key])
                    return row_dict[key]
            logger.warning("  - None of the candidate keys found in the row.")
            return None

        account_id_keys = ["アカウントID", "account_id", "アカウント ID"]
        account_name_keys = ["アカウント名", "account_name", "アカウント 名"]

        logger.info("--- Attempting to extract 'account_id' ---")
        account_id = get_value_from_keys(row, account_id_keys)
        logger.info("--- Attempting to extract 'account_name' ---")
        account_name = get_value_from_keys(row, account_name_keys)

        # ★★★ デバッグログポイント 2: 抽出したアカウント情報を表示 ★★★
        # `row.get`の結果、account_idがどうなったかを確認します。
        logger.info("Extracted account_id: %s, account_name: %s", account_id, account_name)

        # 1. 数値評価を SurveyResponse テーブルに保存 (1行につき1レコード)
        survey_response_data = {
            "file_id": file_record.file_id,
            "account_id": account_id,
            "account_name": account_name,
        }
        for col_name, attr_name in score_column_map.items():
            if col_name in row and row[col_name] and row[col_name].isdigit():
                survey_response_data[attr_name] = int(row[col_name])
        
        survey_response_record = models.SurveyResponse(**survey_response_data)
        db.add(survey_response_record)
        # ★★★ 修正点 ★★★
        # この時点で一度flushを実行し、survey_response_record.id を確定させる。
        # これにより、後続のCommentオブジェクトが正しいIDを参照できるようになる。
        db.flush()

        # 2. 自由記述コメントを Comment テーブルに保存 (複数レコードの可能性あり)
        for column_name, comment_text in _extract_comment_texts(
            row, analyzable_columns
        ):
            # このコメントがLLM分析の対象かどうかを判定
            should_analyze_with_llm = column_name.startswith(LLM_ANALYSIS_TARGET_PREFIX)

            total_comments += 1

            analysis_result = analyze_comment(
                comment_text,
                course_name=file_record.course_name,
                question_text=column_name,
                # LLM分析が不要な場合は、フラグを渡して処理をスキップさせる
                skip_llm_analysis=not should_analyze_with_llm,
            )
            if analysis_result.warnings:
                logger.warning(
                    "LLM warnings for comment: %s",
                    "; ".join(analysis_result.warnings),
                )

            comment_to_add = models.Comment(
                survey_response_id=survey_response_record.id,
                file_id=file_record.file_id,
                account_id=account_id,
                account_name=account_name,
                question_text=column_name,
                comment_text=comment_text,
                llm_category=analysis_result.category,
                llm_sentiment=analysis_result.sentiment_normalized.value
                if analysis_result.sentiment_normalized
                else None,
                llm_summary=analysis_result.summary,
                llm_importance_level=analysis_result.importance_level,
                llm_importance_score=analysis_result.importance_score,
                llm_risk_level=analysis_result.risk_level,
                processed_at=datetime.utcnow(),
            )

            # ★★★ デバッグログポイント 3: DBに保存する直前のオブジェクト内容を表示 ★★★
            # DBに保存する直前のCommentオブジェクトの内容をログに出力
            # ここで account_id が None になっていれば、問題はこれより前のステップにあります。
            logger.info("Attempting to save Comment object with data: %s", comment_to_add.__dict__)
            db.add(comment_to_add)
            processed_comments += 1

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
        name for name in normalized_fieldnames if name.startswith(COMMENT_SAVE_TARGET_PREFIXES)
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
