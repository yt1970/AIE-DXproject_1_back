# app/api/comments.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、完了した分析結果をクライアントに提供するためのAPIエンドポイントを定義します。
# 特定の講義に関連するコメントの分析結果を一覧で取得する機能などを担います。
# ----------------------------------------------------------------------

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, contains_eager, joinedload

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


# C. 分析結果の取得
@router.get(
    "/lectures/{lecture_name}/{lecture_year}/comments",  # 修正済み
    response_model=List[CommentAnalysisSchema],
)
def get_analysis_results(
    lecture_name: str,
    lecture_year: int,
    limit: int = 100,
    skip: int = 0,
    db: Session = Depends(get_db),
):
    """
    指定された講義(`lecture_name`, `lecture_year`)に関連する分析済みコメントの一覧を取得します。

    - **処理の流れ**:
      1. `lecture_name` と `lecture_year` をキーに、関連するテーブルをすべてJOINします。
      2. `contains_eager` を使い、1回のクエリでCommentとそれに関連するStudent, Lecture, CommentAnalysisの情報をすべて取得します（N+1問題の回避）。
      3. 取得したDBモデルのリストを、FastAPIが自動で `CommentAnalysisSchema` のリストに変換して返却します。
    """

    # --- 1. データベースから分析結果を取得 ---
    comments = (
        db.query(models.Comment)
        # 必要なテーブルをすべてJOINする
        .join(
            models.Submission,
            models.Comment.submission_id == models.Submission.submission_id,
        )
        .join(
            models.Enrollment,
            models.Submission.enrollment_id == models.Enrollment.enrollment_id,
        )
        .join(models.Lecture, models.Enrollment.lecture_id == models.Lecture.lecture_id)
        .join(models.Student, models.Enrollment.student_id == models.Student.account_id)
        .outerjoin(
            models.CommentAnalysis,
            models.Comment.comment_id == models.CommentAnalysis.comment_id,
        )  # 分析結果はまだ無いかもしれないのでOUTER JOIN

        # フィルタリング
        .filter(
            models.Lecture.lecture_name == lecture_name,
            models.Lecture.lecture_year == lecture_year,
        )
        # JOINしたテーブルのデータを効率的に読み込むための設定
        .options(
            # joinedload を使ってリレーション先のデータをJOINして取得する
            # これにより、Commentオブジェクトから .analysis や .submission.enrollment.student などに
            # アクセスした際に追加のクエリが発行されるのを防ぐ (N+1問題の回避)
            joinedload(models.Comment.analysis),
            joinedload(models.Comment.submission)
            .joinedload(models.Submission.enrollment)
            .joinedload(models.Enrollment.student),
            joinedload(models.Comment.submission)
            .joinedload(models.Submission.enrollment)
            .joinedload(models.Enrollment.lecture),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    # --- 2. 結果を返却 ---
    return comments


@router.get(
    "/courses/{course_name}/comments",
    response_model=List[CommentAnalysisSchema],
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

    comments = (
        db.query(models.Comment)
        .join(models.UploadedFile, models.Comment.file_id == models.UploadedFile.file_id)
        .filter(models.UploadedFile.course_name == course_name)
        .order_by(models.Comment.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return comments
