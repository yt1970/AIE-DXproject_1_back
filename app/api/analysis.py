# app/api/analysis.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、非同期で実行される分析ジョブの進捗状況をクライアントに提供するための
# APIエンドポイントを定義します。
# ----------------------------------------------------------------------

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.comment import AnalysisStatusResponse

router = APIRouter()


@router.get("/jobs/{job_id}/status", response_model=AnalysisStatusResponse)
def get_analysis_status(
    job_id: int,
    db: Session = Depends(get_db),
):
    """
    指定されたjob_idに対応する分析ジョブのステータスを返します。

    - **データ処理の流れ**:
      1. クライアントから `job_id` を含むGETリクエストを受け取ります。
      2. `job_id` をキーにして `analysis_jobs` テーブルを検索します。
      3. レコードが見つかれば、その内容を `AnalysisStatusResponse` の形式でクライアントに返します。
      4. レコードが見つからなければ、404 Not Foundエラーを返します。
    """
    job = (
        db.query(models.AnalysisJob).filter(models.AnalysisJob.job_id == job_id).first()
    )

    if not job:
        raise HTTPException(status_code=404, detail=f"Job with id {job_id} not found")

    return job
