# app/api/upload.py

# ----------------------------------------------------------------------
# このファイル全体の役割
# ----------------------------------------------------------------------
# このファイルは、クライアントからのファイルアップロード要求を処理するAPIエンドポイントを定義します。
# アップロードされたファイルのメタデータをデータベースに記録し、
# バックグラウンドでの非同期分析タスクを開始するきっかけとなる役割を持ちます。
# ----------------------------------------------------------------------

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db

# --- 内部モジュールのインポート ---
from app.schemas.comment import UploadRequestMetadata, UploadResponse

metadata_adapter = TypeAdapter(UploadRequestMetadata)

# ----------------------------------------------------------------------
# ルーターの初期化
# ----------------------------------------------------------------------
router = APIRouter()

# ----------------------------------------------------------------------
# エンドポイントの定義
# ----------------------------------------------------------------------


# A. ファイルアップロードと非同期処理の開始
@router.post("/uploads", response_model=UploadResponse)
async def upload_and_start_analysis(
    # `Annotated[...]`: Python 3.9+ の型ヒント機能。FastAPIはこれを見て引数の詳細を解釈します。
    # `File()`: この引数がファイルアップロードデータであることを示します。
    file: Annotated[UploadFile, File()],
    # `Form()`: この引数がフォームデータ（`multipart/form-data`）から取得することを示します。
    # メタデータはJSON文字列として送信されることを想定しています。
    metadata_json: Annotated[str, Form(alias="metadata")],
    # `Depends(get_db)`: データベースセッションを取得します。
    db: Session = Depends(get_db),
):
    """
    クライアントからアップロードされたファイルとメタデータを受け取り、DBに記録します。

    - **この修正の目的**:
      これまでのダミー実装とは異なり、この関数は実際にデータベースと連携します。
      アップロードされたファイルの情報を `uploaded_file` テーブルに永続化（保存）し、
      後続の分析処理で参照できるようにすることが、この修正の主な目的です。

    - **処理の流れ**:
      1. `metadata_json`（JSON文字列）を Pydanticモデル `UploadRequestMetadata` にパース（変換）して検証します。
      2. （将来的に）ファイルをS3などのストレージに保存します。
      3. パースしたメタデータとファイル情報を使って `UploadedFile` モデルを作成します。
      4. 作成したモデルをDBセッションに追加し、コミットしてデータベースに保存します。
      5. DBによって自動採番された `file_id` を取得し、クライアントに返却します。
    """

    # --- 1. メタデータのパースと検証 ---
    try:
        # TypeAdapterを利用し、JSON文字列をPydanticモデルに変換して検証します。
        metadata = metadata_adapter.validate_json(metadata_json)
    except (ValidationError, json.JSONDecodeError) as e:
        # パースや検証に失敗した場合は、クライアントの入力が不正であるため、
        # HTTP 422 Unprocessable Entity エラーを返します。
        raise HTTPException(status_code=422, detail=f"Invalid metadata format: {e}")

    # --- 2. （将来の実装）ファイルストレージへの保存 ---
    # ここに、受け取った `file` をS3などにアップロードし、そのパス(s3_key)を取得するコードが入ります。
    # current_s3_key = await save_to_s3(file)
    # 現時点ではダミーの文字列を入れます。
    current_s3_key = f"s3://bucket-name/path/to/{file.filename}"

    # --- 3. データベースモデルのインスタンスを作成 ---
    # `app/db/models.py` で定義した `UploadedFile` クラスのインスタンスを作成します。
    # APIで受け取ったデータを、DBテーブルの各カラムに対応させます。
    new_file_record = models.UploadedFile(
        course_name=metadata.course_name,
        lecture_date=metadata.lecture_date,
        lecture_number=metadata.lecture_number,
        status="PENDING",  # アップロード直後のステータスは「処理待ち」
        s3_key=current_s3_key,
        upload_timestamp=datetime.utcnow(),  # 現在のUTC時刻
    )

    # --- 4. データベースへの保存処理 ---
    try:
        # `db.add()`: 作成したレコードを、このトランザクションで「追加」する対象としてマークします。
        db.add(new_file_record)
        # `db.commit()`: これまでの変更（この場合は`add`）をデータベースに永続的に書き込みます。
        db.commit()
        # `db.refresh()`: DBに書き込んだ後、DB側で自動採番されたIDなど、
        # 最新の状態を `new_file_record` インスタンスに反映させます。
        db.refresh(new_file_record)
    except Exception as e:
        # ユニークキー制約違反など、DBへの書き込み中にエラーが発生した場合
        db.rollback()  # トランザクションをロールバック（変更を取り消し）します。
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    # --- 5. 成功レスポンスを返却 ---
    # `new_file_record.file_id` には、DBで自動採番されたIDが入っています。
    # これをクライアントに返すことで、後続のステータス確認で利用できるようにします。
    return UploadResponse(
        file_id=new_file_record.file_id,
        status_url=f"/api/v1/uploads/{new_file_record.file_id}/status",
        message="Upload successful. Analysis has been queued.",
    )
