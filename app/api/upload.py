# app/api/upload.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、クライアントからのCSVファイルアップロード要求を処理するAPIエンドポイントを定義します。
# 非同期処理を想定した設計になっており、以下の責務を持ちます。
# 1. ファイルアップロードを受け付け、基本的な検証を行う。
# 2. 時間のかかる分析処理の「ジョブ」をDBに登録する。
# 3. 実際の分析処理は行わず、クライアントに即座に「ジョブID」を返す。
# (注: このバージョンでは分析処理も同期的に実行していますが、APIのインターフェースは非同期設計です)
# ----------------------------------------------------------------------

import csv
import io
import json
import logging
from datetime import datetime
from typing import Annotated, Dict

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

router = APIRouter()

STUDENT_ID_COLUMN = "account_id"


@router.post("/uploads", response_model=UploadResponse)
async def upload_and_run_analysis_sync(
    file: Annotated[UploadFile, File()],
    metadata_json: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    """
    CSVファイルのアップロードを受け付け、分析ジョブを作成し、同期的に分析を実行します。

    - **データ処理の流れ**:
      1.  クライアントからファイルとメタデータを受け取ります。
      2.  講義情報(Lecture)をDBから取得、または新規作成します。
      3.  分析ジョブ(AnalysisJob)をDBに作成し、ステータスを 'PENDING' にします。
          この時点でクライアントに返すためのジョブIDが確定します。
      4.  ジョブのステータスを 'PROCESSING' に更新します。
      5.  CSVの各行をループ処理し、DBにデータを保存していきます。
          - 受講生(Student), 受講登録(Enrollment)を取得/作成。
          - 回答(Submission)とコメント(Comment)を作成。
          - コメントごとにLLM分析(CommentAnalysis)を実行・保存。
          - 1行処理するごとにジョブの進捗(processed_submissions)を更新します。
      6.  すべての行の処理が終わったら、ジョブのステータスを 'COMPLETED' に更新します。
      7.  もし途中でエラーが発生したら、ジョブのステータスを 'FAILED' にし、エラー内容を記録します。
      8.  処理の成否に関わらず、ステップ3で確定したジョブIDを含む応答をクライアントに返します。
    """
    try:
        # --- 1. メタデータとCSVファイルの読み込み・検証 ---
        metadata = metadata_adapter.validate_json(metadata_json)
        content_bytes = await file.read()
        content_text = content_bytes.decode("utf-8-sig")
        csv_reader = csv.DictReader(io.StringIO(content_text))
        if not csv_reader.fieldnames or STUDENT_ID_COLUMN not in csv_reader.fieldnames:
            raise HTTPException(
                status_code=400,
                detail=f"CSV must contain '{STUDENT_ID_COLUMN}' column.",
            )
        rows = list(csv_reader)  # 先に全行をメモリに読み込む
    except (ValidationError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid metadata format: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

    # --- 1.5 DBからカラムマッピング情報を取得 ---
    mappings = db.query(models.ColumnMapping).filter_by(is_active=True).all()
    comment_column_mapping = {
        m.csv_header: models.CommentType[m.db_column_name]
        for m in mappings
        if m.mapping_type == models.MappingType.COMMENT
    }
    score_column_mapping = {
        m.csv_header: m.db_column_name
        for m in mappings
        if m.mapping_type == models.MappingType.SCORE
    }

    # --- 2. 講義情報(Lecture)の取得または作成 (Get-or-Create) ---
    lecture = (
        db.query(models.Lecture)
        .filter_by(
            lecture_name=metadata.lecture_name, lecture_year=metadata.lecture_date.year
        )
        .first()
    )
    if not lecture:
        lecture = models.Lecture(
            lecture_name=metadata.lecture_name, lecture_year=metadata.lecture_date.year
        )
        db.add(lecture)
        db.flush()

    # --- 3. 分析ジョブ(AnalysisJob)の作成 ---
    job = models.AnalysisJob(
        lecture_id=lecture.lecture_id,
        status="PENDING",
        original_filename=file.filename,
        total_submissions=len(rows),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # --- 4. ここから同期的な分析処理を開始 ---
    try:
        # ステータスを 'PROCESSING' に更新
        job.status = "PROCESSING"
        db.commit()

        # --- 5. CSVの各行をループ処理 ---
        for row in rows:
            student_id = row.get(STUDENT_ID_COLUMN)
            if not student_id:
                continue

            # Get-or-Createロジック
            student = db.query(models.Student).filter_by(account_id=student_id).first()
            if not student:
                student = models.Student(
                    account_id=student_id, account_name=row.get("account_name")
                )
                db.add(student)
                db.flush()

            enrollment = (
                db.query(models.Enrollment)
                .filter_by(student_id=student.account_id, lecture_id=lecture.lecture_id)
                .first()
            )
            if not enrollment:
                enrollment = models.Enrollment(
                    student_id=student.account_id, lecture_id=lecture.lecture_id
                )
                db.add(enrollment)
                db.flush()

            # Submission, Comment, CommentAnalysis の作成
            submission_data = {
                db_col: row.get(csv_col)
                for csv_col, db_col in score_column_mapping.items()
            }
            submission = models.Submission(
                enrollment_id=enrollment.enrollment_id, **submission_data
            )
            db.add(submission)
            db.flush()

            for col_name, comment_type in comment_column_mapping.items():
                comment_text = row.get(col_name, "").strip()
                if comment_text:
                    new_comment = models.Comment(
                        submission_id=submission.submission_id,
                        comment_type=comment_type,
                        comment_text=comment_text,
                    )
                    db.add(new_comment)
                    db.flush()

                    analysis_result = analyze_comment(comment_text)
                    new_analysis = models.CommentAnalysis(
                        comment_id=new_comment.comment_id,
                        is_improvement_needed=analysis_result.is_improvement_needed,
                        is_slanderous=analysis_result.is_slanderous,
                        sentiment=analysis_result.sentiment,
                        analyzed_at=datetime.utcnow(),
                    )
                    db.add(new_analysis)

            # ジョブの進捗を更新
            job.processed_submissions += 1
            db.commit()

        # --- 6. ジョブのステータスを 'COMPLETED' に更新 ---
        job.status = "COMPLETED"
        job.completed_at = datetime.utcnow()
        db.commit()

    except Exception as e:  # --- 7. エラー処理 ---
        logger.exception(f"Analysis job {job.job_id} failed.")
        db.rollback()
        job.status = "FAILED"
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()
        # エラーが発生しても、クライアントにはジョブIDを返す。詳細はステータスAPIで確認させる。

    # --- 8. 成功レスポンスを返却 ---
    return UploadResponse(
        job_id=job.job_id,
        status_url=f"/api/v1/jobs/{job.job_id}/status",
        message="Analysis job has been accepted. Check status URL for progress.",
    )
