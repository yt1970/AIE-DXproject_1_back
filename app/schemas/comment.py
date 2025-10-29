from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import CommentType, SentimentType

# ----------------------------------------------------------------------
# 📤 (出力) スキーマ
# APIがクライアントに返すデータの「形」を定義します。
# ----------------------------------------------------------------------

class UploadResponse(BaseModel):
    """
    ファイルアップロード受付成功時に返すレスポンスのスキーマ。
    重い処理の完了を待たずに、即座にジョブIDとステータス確認用URLを返却します。
    これにより、クライアントは長時間待たされることがなくなります。
    """
    job_id: int
    status_url: str
    message: str


class LectureSchema(BaseModel):
    """講義情報のスキーマ。"""
    lecture_id: int
    lecture_name: str
    lecture_year: int


class StudentSchema(BaseModel):
    """受講生情報のスキーマ。"""
    account_id: str
    account_name: Optional[str] = None


class AnalysisDetailSchema(BaseModel):
    """LLMによる分析結果詳細のスキーマ。"""
    is_improvement_needed: bool
    is_slanderous: bool
    sentiment: Optional[SentimentType] = None
    analyzed_at: datetime


class CommentAnalysisSchema(BaseModel):
    """
    APIで返す、集約されたコメント分析結果のスキーマ。
    複数のDBテーブルから情報を結合してこの形を構築します。
    """
    comment_id: int
    comment_type: CommentType
    comment_text: str
    analysis: Optional[AnalysisDetailSchema] = None
    student: StudentSchema
    lecture: LectureSchema

    # Pydantic V2の設定。DBモデルの属性から自動でPydanticモデルを生成できるようにする。
    model_config = ConfigDict(from_attributes=True)


class AnalysisStatusResponse(BaseModel):
    """
    分析ジョブのステータス確認APIのレスポンススキーマ。
    クライアントは status_url (例: /api/v1/jobs/{job_id}/status) にリクエストを送り、
    このスキーマで定義された形式でジョブの進捗状況を受け取ります。
    """
    job_id: int
    status: str
    total_submissions: int
    processed_submissions: int
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

# ----------------------------------------------------------------------
# 📥 (入力) スキーマ
# クライアントからAPIが受け取るデータの「形」を定義します。
# ----------------------------------------------------------------------

class UploadRequestMetadata(BaseModel):
    """ファイルアップロード時にクライアントから受け取るメタデータのスキーマ。"""
    lecture_name: str
    lecture_date: date
    uploader_id: Optional[int] = None
