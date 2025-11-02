# app/api/comments.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、完了した分析結果をクライアントに提供するためのAPIエンドポイントを定義します。
# 特定の講義に関連するコメントの分析結果を一覧で取得する機能などを担います。
# ----------------------------------------------------------------------

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, contains_eager

from app.db import models
from app.db.session import get_db

# --- 内部モジュールのインポート ---
from app.schemas.comment import CommentAnalysisSchema

# ----------------------------------------------------------------------
# ルーターの初期化
# ----------------------------------------------------------------------
router = APIRouter()

# ----------------------------------------------------------------------
# エンドポイントの定義
# ----------------------------------------------------------------------

@router.get(
    "/courses/{course_name}/comments",
    response_model=List[CommentAnalysisSchema]
    )
def get_course_comments(
    course_name: str,
    limit: int = 100,
    skip: int = 0,
    db: Session = Depends(get_db),
):
    """
    講義名単位で最新のコメント分析結果を取得する。
    """

    comments_with_scores = (
        db.query(models.Comment)
        # Comment -> UploadedFile のJOIN
        .join(models.UploadedFile, models.Comment.file_id == models.UploadedFile.file_id)
        # Comment -> SurveyResponse のJOIN
        # outerjoin を使うことで、数値評価が存在しないコメントも取得できるようにします。
        .outerjoin(models.Comment.survey_response)
        .filter(models.UploadedFile.course_name == course_name)
        # optionsを使って、関連するデータを1回のクエリで効率的に読み込む(N+1問題の防止)
        .options(
            contains_eager(models.Comment.uploaded_file),
            contains_eager(models.Comment.survey_response),
        )
        .order_by(models.Comment.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return comments_with_scores
