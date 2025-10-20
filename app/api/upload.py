# app/api/upload.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、クライアントからのファイルアップロード要求を処理するAPIエンドポイントを定義します。
# アップロードされたCSVファイルから任意コメント列を抽出し、
# 同期的に分析して結果をDBに保存する役割を担います。
# ----------------------------------------------------------------------

import csv
import io
import json
import logging
import re
from datetime import datetime
from typing import Annotated, List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

# --- 内部モジュールのインポート ---
from app.analysis.analyzer import analyze_comment
from app.db import models
from app.db.session import get_db
from app.schemas.comment import UploadRequestMetadata, UploadResponse
from app.services import StorageError, get_storage_client

metadata_adapter = TypeAdapter(UploadRequestMetadata)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# ルーターの初期化
# ----------------------------------------------------------------------
router = APIRouter()

# ----------------------------------------------------------------------
# エンドポイントの定義
# ----------------------------------------------------------------------


COMMENT_ANALYSIS_PREFIX = "（任意）"


# A. ファイルアップロードと同期分析の実行
@router.post("/uploads", response_model=UploadResponse)
async def upload_and_run_analysis_sync(
    file: Annotated[UploadFile, File()],
    metadata_json: Annotated[str, Form(alias="metadata")],
    db: Session = Depends(get_db),
):
    """
    クライアントからアップロードされたCSVファイルを同期的に分析し、結果をDBに保存します。

    - **この修正の目的**:
      CSVヘッダーから「（任意）…」で始まるコメント列のみを抽出し、各セルを分析対象として扱います。

    - **処理の流れ**:
      1.  `metadata_json` をパース・検証します。
      2.  メタデータから `UploadedFile` レコードを作成し、ステータスを `PENDING` としてDBに一度保存します。
      3.  アップロードされたCSVファイルを読み込み、1行ずつ辞書として反復処理します。
      4.  各行で「（任意）…」列を順番に走査し、空でないテキストだけを抽出します。
      5.  抽出した各テキストを `analyze_comment` に渡してLLM分析を実行します。
      6.  分析結果を `Comment` レコードとして保存します。
      7.  処理したコメント件数を `UploadedFile` レコードに記録し、`COMPLETED` ステータスへ更新します。
      8.  トランザクションをコミットし、すべての変更をDBに反映します。
      9.  成功レスポンスをクライアントに返却します。
    """

    # --- 1. メタデータのパースと検証 ---
    try:
        metadata = metadata_adapter.validate_json(metadata_json)
    except (ValidationError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid metadata format: {e}")

    # --- 2. ファイル内容の読み込みと基本検証 ---
    try:
        content_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to read uploaded file: {exc}"
        )

    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        content_text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"CSV must be UTF-8 encoded: {exc}")

    csv_stream = io.StringIO(content_text)
    csv_reader = csv.DictReader(csv_stream)

    if not csv_reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is missing.")

    normalized_fieldnames = [header.strip() for header in csv_reader.fieldnames]

    if any(not header for header in normalized_fieldnames):
        raise HTTPException(
            status_code=400,
            detail="CSV header contains an empty column name.",
        )

    if len(set(normalized_fieldnames)) != len(normalized_fieldnames):
        raise HTTPException(
            status_code=400,
            detail="CSV header contains duplicate column names after normalization.",
        )

    analyzable_columns = _extract_analyzable_columns(normalized_fieldnames)

    csv_reader.fieldnames = normalized_fieldnames

    # --- 3. ストレージへファイルを保存 ---
    storage_client = get_storage_client()
    storage_relative_path = _build_storage_path(metadata, file.filename)
    try:
        stored_location = storage_client.save(
            relative_path=storage_relative_path,
            data=content_bytes,
            content_type=file.content_type,
        )
    except StorageError as exc:
        logger.exception("Failed to persist uploaded file.")
        raise HTTPException(
            status_code=500, detail="Failed to persist uploaded file."
        ) from exc

    # --- 4. UploadedFileレコードの作成 ---
    new_file_record = models.UploadedFile(
        course_name=metadata.course_name,
        lecture_date=metadata.lecture_date,
        lecture_number=metadata.lecture_number,
        status="PENDING",
        s3_key=stored_location,
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
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database error on creating file record: {e}"
        )

    # --- 5. CSVファイルを読み込み、コメントを1行ずつ分析・保存 ---
    total_comments = 0
    processed_comments = 0
    try:
        for row in csv_reader:
            comment_texts = _extract_comment_texts(row, analyzable_columns)

            for comment_text in comment_texts:
                total_comments += 1

                # --- 6. 分析の実行 ---
                analysis_result = analyze_comment(comment_text)

                if analysis_result.warnings:
                    logger.warning(
                        "LLM warnings for comment: %s",
                        "; ".join(analysis_result.warnings),
                    )

                processed_comments += 1

                # --- 7. Commentレコードの作成 ---
                new_comment = models.Comment(
                    file_id=new_file_record.file_id,
                    comment_text=comment_text,
                    llm_category=analysis_result.category,
                    llm_sentiment=analysis_result.sentiment,
                    llm_summary=analysis_result.summary,
                    llm_importance_level=analysis_result.importance_level,
                    llm_importance_score=analysis_result.importance_score,
                    llm_risk_level=analysis_result.risk_level,
                    processed_at=datetime.utcnow(),
                )
                db.add(new_comment)

        # --- 8. ファイルのステータスを更新 ---
        new_file_record.status = "COMPLETED"
        new_file_record.total_rows = total_comments
        new_file_record.processed_rows = processed_comments
        db.add(new_file_record)

        # --- 9. トランザクションのコミット ---
        db.commit()

    except Exception as e:
        db.rollback()
        new_file_record.status = "FAILED"
        new_file_record.total_rows = total_comments
        new_file_record.processed_rows = processed_comments
        db.add(new_file_record)
        db.commit()
        raise HTTPException(
            status_code=500, detail=f"Error during analysis process: {e}"
        )

    # --- 10. 成功レスポンスを返却 ---
    return UploadResponse(
        file_id=new_file_record.file_id,
        status_url=f"/api/v1/uploads/{new_file_record.file_id}/status",
        message="Upload and analysis successful.",
    )


def _extract_analyzable_columns(fieldnames: List[str]) -> List[str]:
    analyzable = [name for name in fieldnames if name.startswith(COMMENT_ANALYSIS_PREFIX)]
    if not analyzable:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain at least one column whose header starts with '（任意）'.",
        )
    return analyzable


def _extract_comment_texts(row: dict, analyzable_columns: List[str]) -> List[str]:
    comment_texts: List[str] = []
    for column in analyzable_columns:
        value = _normalize_cell(row.get(column))
        if value:
            comment_texts.append(value)
    return comment_texts


def _build_storage_path(metadata: UploadRequestMetadata, filename: str | None) -> str:
    course = _slugify(metadata.course_name)
    lecture_segment = (
        f"{metadata.lecture_date.isoformat()}-lecture-{metadata.lecture_number}"
    )
    safe_filename = _slugify(filename or "uploaded.csv", allow_period=True)
    return "/".join((course, lecture_segment, f"{uuid4().hex}_{safe_filename}"))


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
