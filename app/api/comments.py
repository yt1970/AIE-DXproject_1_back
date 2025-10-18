# app/api/comments.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、完了した分析結果をクライアントに提供するためのAPIエンドポイントを定義します。
# 特定の講義に関連するコメントの分析結果を一覧で取得する機能などを担います。
# ----------------------------------------------------------------------

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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
    "/courses/{course_name}/comments", response_model=List[CommentAnalysisSchema]
)
def get_analysis_results(
    course_name: str, limit: int = 100, skip: int = 0, db: Session = Depends(get_db)
):
    """
    指定された講義名(`course_name`)に関連する分析済みコメントの一覧を取得します。

    - **この修正の目的**:
      これまでの空のリストを返すダミー実装から、実際にデータベースを検索して
      分析結果を返すように変更します。ページネーション機能（limit/skip）も実装し、
      大量のデータがあっても効率的に結果を返せるようにします。

    - **処理の流れ**:
      1. `course_name` をキーにして、`Comment` テーブルと `UploadedFile` テーブルを結合（JOIN）して検索します。
         これにより、特定の講義に紐づくコメントのみを抽出します。
      2. `skip` と `limit` を使って、取得する結果の範囲を指定します（ページネーション）。
      3. 取得したDBモデルのリストを、FastAPIが自動で `response_model` (`CommentAnalysisSchema`) のリストに変換して返却します。
         (これは `CommentAnalysisSchema` の `Config.from_attributes = True` 設定のおかげで機能します)
    """

    # --- 1. データベースから分析結果を取得 ---
    # `db.query(models.Comment)`: `comment` テーブルへのクエリを開始します。
    # `.join(models.UploadedFile)`: `Comment` モデルと `UploadedFile` モデルを、
    #   リレーションシップ定義に基づいて内部結合（INNER JOIN）します。
    # `.filter(models.UploadedFile.course_name == course_name)`:
    #   結合した結果から、`uploaded_file` テーブルの `course_name` が指定されたものと一致するレコードのみを絞り込みます。
    # `.offset(skip)`: `skip` で指定された件数分のレコードを読み飛ばします。
    # `.limit(limit)`: `limit` で指定された最大件数分のレコードを取得します。
    # `.all()`: 条件に一致したすべてのレコードをリストとして取得します。
    comments = (
        db.query(models.Comment)
        .join(models.UploadedFile)
        .filter(models.UploadedFile.course_name == course_name)
        .offset(skip)
        .limit(limit)
        .all()
    )

    # --- 2. 結果を返却 ---
    # SQLAlchemyモデルのリストをそのまま返します。
    # FastAPIが `response_model` に基づいてPydanticモデルのリストに自動変換してくれます。
    return comments
