from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

from app.db.models import CommentType, SentimentType

# ----------------------------------------------------------------------
# 📤 (出力) スキーマ
# ----------------------------------------------------------------------

# ファイルアップロード成功時の応答
class UploadResponse(BaseModel):
    lecture_id: int
    submissions_processed: int
    comments_analyzed: int
    message: str


# 講義情報
class LectureSchema(BaseModel):
    lecture_id: int
    lecture_name: str
    lecture_year: int


# 受講生情報
class StudentSchema(BaseModel):
    account_id: str
    account_name: Optional[str] = None


# 分析結果の詳細
class AnalysisDetailSchema(BaseModel):
    is_improvement_needed: bool
    is_slanderous: bool
    sentiment: Optional[SentimentType] = None
    analyzed_at: datetime


# APIで返す、集約されたコメント分析結果
class CommentAnalysisSchema(BaseModel):
    comment_id: int
    comment_type: CommentType
    comment_text: str
    analysis: Optional[AnalysisDetailSchema] = None
    student: StudentSchema
    lecture: LectureSchema

    class Config:
        from_attributes = True # DBモデルからの変換を許可

# ----------------------------------------------------------------------
# 📥 (入力) スキーマ
# ----------------------------------------------------------------------

# ファイルアップロード時にクライアントから受け取るメタデータ
class UploadRequestMetadata(BaseModel):
    course_name: str
    lecture_date: date
    uploader_id: Optional[int] = None
