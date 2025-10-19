# app/api/upload.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、クライアントからのファイルアップロード要求を処理するAPIエンドポイントを定義します。
# アップロードされたCSVファイル（受講生IDとコメントを含む）を解析し、
# 同期的に分析して結果をDBに保存する役割を担います。
# ----------------------------------------------------------------------

import csv
import io
import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

# --- 内部モジュールのインポート ---
from app.analysis.analyzer import analyze_comment
from app.db import models
from app.db.session import get_db
from app.schemas.comment import UploadRequestMetadata, UploadResponse

metadata_adapter = TypeAdapter(UploadRequestMetadata)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# ルーターの初期化
# ----------------------------------------------------------------------
router = APIRouter()

# ----------------------------------------------------------------------
# エンドポイントの定義
# ----------------------------------------------------------------------


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
      アップロードされるファイルが `student_id` と `comment` の列を持つCSVであるという前提のもと、
      ファイル内の各コメントを分析し、正しい受講生IDに紐づけて結果を永続化します。

    - **処理の流れ**:
      1.  `metadata_json` をパース・検証します。
      2.  メタデータから `UploadedFile` レコードを作成し、ステータスを `PENDING` としてDBに一度保存します。
      3.  アップロードされたCSVファイルを読み込み、1行ずつ辞書として反復処理します。
      4.  各行から `student_id` と `comment` を取得します。
      5.  （堅牢性のため）`student_id` を持つ `Student` レコードがDBに存在しない場合は、仮のレコードを作成します。
      6.  コメントに対して `analyze_comment` 関数を呼び出し、分析結果を取得します。
      7.  分析結果と `student_id` を使って `Comment` レコードを作成し、DBセッションに追加します。
      8.  すべてのコメントの処理が終わったら、`UploadedFile` レコードのステータスを `COMPLETED` に更新します。
      9.  トランザクションをコミットし、すべての変更をDBに反映します。
      10. 成功レスポンスをクライアントに返却します。
    """

    # --- 1. メタデータのパースと検証 ---
    try:
        metadata = metadata_adapter.validate_json(metadata_json)
    except (ValidationError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid metadata format: {e}")

    # --- 2. UploadedFileレコードの作成 ---
    current_s3_key = f"s3://bucket-name/path/to/{file.filename}"
    new_file_record = models.UploadedFile(
        course_name=metadata.course_name,
        lecture_date=metadata.lecture_date,
        lecture_number=metadata.lecture_number,
        status="PENDING",
        s3_key=current_s3_key,
        upload_timestamp=datetime.utcnow(),
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

    # --- 3. CSVファイルを読み込み、コメントを1行ずつ分析・保存 ---
    try:
        content_bytes = await file.read()
        content_text = content_bytes.decode("utf-8")
        csv_reader = csv.DictReader(io.StringIO(content_text))

        for row in csv_reader:
            student_id = row.get("student_id")
            comment_text = row.get("comment")

            if not student_id or not comment_text:
                continue  # 必須データがない行はスキップ

            # --- 5. Studentレコードの存在確認と作成（なければ） ---
            student = (
                db.query(models.Student)
                .filter(models.Student.student_id == student_id)
                .first()
            )
            if not student:
                student = models.Student(
                    student_id=student_id,
                    email_address=f"{student_id}@example.com",  # 仮のメールアドレス
                    created_at=datetime.utcnow(),
                )
                db.add(student)

            # --- 6. 分析の実行 ---
            analysis_result = analyze_comment(comment_text)

            if analysis_result.warnings:
                logger.warning(
                    "LLM warnings for student_id=%s: %s",
                    student_id,
                    "; ".join(analysis_result.warnings),
                )

            # --- 7. Commentレコードの作成 ---
            new_comment = models.Comment(
                file_id=new_file_record.file_id,
                student_id=student_id,  # CSVから取得したIDを使用
                comment_learned_raw=comment_text,
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
        db.add(new_file_record)

        # --- 9. トランザクションのコミット ---
        db.commit()

    except Exception as e:
        db.rollback()
        new_file_record.status = "FAILED"
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
