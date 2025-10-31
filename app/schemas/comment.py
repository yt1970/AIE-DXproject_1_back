from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


# 📤 (出力) ファイルアップロード成功時の応答スキーマ
class UploadResponse(BaseModel):
    file_id: int
    status_url: str
    message: str


# 📥 (入力) ファイルアップロード時に必要なメタデータスキーマ
class UploadRequestMetadata(BaseModel):
    # 講義の複合識別子をフロントエンドから受け取る
    course_name: str
    lecture_date: date  # 日付型
    lecture_number: int

    # 誰がアップロードしたかの情報（任意）
    uploader_id: Optional[int] = None


# 📊 (出力) ステータス確認時の応答スキーマ
class AnalysisStatusResponse(BaseModel):
    file_id: int
    status: str
    total_comments: int
    processed_count: int
    task_id: Optional[str] = None
    queued_at: datetime
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


# 📝 (出力) 分析結果（コメント一覧）のスキーマ
class CommentAnalysisSchema(BaseModel):
    comment_text: str
    llm_category: Optional[str] = None
    llm_sentiment: Optional[str] = None
    llm_summary: Optional[str] = None
    llm_importance_level: Optional[str] = None
    llm_importance_score: Optional[float] = None
    llm_risk_level: Optional[str] = None
    score_satisfaction_overall: Optional[int] = None

    class Config:
        # DBモデルからの変換を許可 (SQLAlchemy ORMとの連携用)
        from_attributes = True
