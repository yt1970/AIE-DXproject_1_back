# app/api/comments.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、完了した分析結果をクライアントに提供するためのAPIエンドポイントを定義します。
# 特定の講義に関連するコメントの分析結果を一覧で取得する機能などを担います。
# ----------------------------------------------------------------------

from typing import List
import logging

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
logger = logging.getLogger(__name__)

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

    # ★★★ デバッグログポイント 4: DBから取得したオブジェクト内容を詳細に表示 ★★★
    # DBから取得した最初のCommentオブジェクトと、関連するSurveyResponseの内容をログに出力します。
    if comments_with_scores:
        first_comment = comments_with_scores[0]
        logger.info("--- Fetched data from DB for API response ---")
        logger.info("First Comment object from DB: %s", first_comment.__dict__)
        if first_comment.survey_response:
            logger.info(
                "Attached SurveyResponse object: %s",
                first_comment.survey_response.__dict__,
            )
        else:
            logger.info("No SurveyResponse attached to the first comment.")

    return comments_with_scores
