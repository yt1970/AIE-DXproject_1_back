# app/api/analysis.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、分析処理に関連するAPIエンドポイントを定義します。
# 主に、バックグラウンドで実行される分析タスクの進捗状況をクライアントに提供する役割を担います。
# ----------------------------------------------------------------------

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# --- 内部モジュールのインポート ---
# Pydanticスキーマ：APIのレスポンスボディの構造を定義
from app.schemas.comment import AnalysisStatusResponse
# データベースモデル：DBテーブルの構造を定義
from app.db import models
# データベースセッション管理：DB接続を取得するための依存性注入関数
from app.db.session import get_db


# ----------------------------------------------------------------------
# ルーターの初期化
# ----------------------------------------------------------------------
# APIRouterインスタンスを作成します。
# main.pyでこのルーターがインクルードされ、エンドポイントがアプリケーションに登録されます。
router = APIRouter()


# ----------------------------------------------------------------------
# エンドポイントの定義
# ----------------------------------------------------------------------

# B. 分析ステータスの確認
@router.get("/analysis/{file_id}/status", response_model=AnalysisStatusResponse)
def get_analysis_status(
    file_id: int,
    # `Depends(get_db)`: FastAPIの依存性注入システム。
    # このエンドポイントが呼ばれるたびにget_db関数が実行され、
    # データベースセッション(db)が提供されます。処理が終わると自動でクローズされます。
    db: Session = Depends(get_db)
):
    '''
    指定されたfile_idに対応するファイルの分析ステータスを返します。

    - **処理の流れ**:
      1. `file_id` を使って、`uploaded_file` テーブルから該当するレコードを検索します。
      2. レコードが見つからない場合は、404エラーを返します。
      3. レコードが見つかった場合は、そのレコードのステータスや関連するコメント数を集計します。
      4. Pydanticモデル `AnalysisStatusResponse` に従って、結果をクライアントに返します。
    '''
    
    # --- 1. データベースからファイル情報を取得 ---
    # `db.query(models.UploadedFile)`: `uploaded_file`テーブルへのクエリを開始します。
    # `.filter(models.UploadedFile.file_id == file_id)`: `file_id`が一致するレコードを絞り込みます。
    # `.first()`: 条件に一致した最初の1件を取得します。見つからなければNoneを返します。
    uploaded_file = db.query(models.UploadedFile).filter(models.UploadedFile.file_id == file_id).first()

    # --- 2. ファイル存在チェック ---
    if not uploaded_file:
        # ファイルが見つからない場合は、HTTP 404 Not Foundエラーを発生させます。
        raise HTTPException(status_code=404, detail=f"File with id {file_id} not found")

    # --- 3. 関連コメントの件数を集計 ---
    # `db.query(models.Comment)`: `comment`テーブルへのクエリを開始します。
    # `.filter(models.Comment.file_id == file_id)`: `file_id`が一致するコメントを絞り込みます。
    # `.count()`: 条件に一致したレコードの総数をカウントします。
    # (注：ここではtotal_commentsは仮で固定値を入れていますが、将来的にはExcelから読み込んだ総数などを保持する想定)
    processed_count = db.query(models.Comment).filter(models.Comment.file_id == file_id).count()
    total_comments = 20000 # 仮の総コメント数

    # --- 4. レスポンスを返却 ---
    # 取得した情報を使って、レスポンス用のPydanticモデルを構築し、返却します。
    return AnalysisStatusResponse(
        file_id=file_id,
        status=uploaded_file.status, # DBから取得したステータス
        total_comments=total_comments,
        processed_count=processed_count # DBから取得した処理済みコメント数
    )