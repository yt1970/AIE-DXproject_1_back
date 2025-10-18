from datetime import date
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

# 📝 (出力) 分析結果（コメント一覧）のスキーマ
class CommentAnalysisSchema(BaseModel):
    comment_learned_raw: str
    comment_improvements_raw: str
    llm_category: str
    llm_summary: str
    score_satisfaction_overall: Optional[int]
    
    class Config:
        # DBモデルからの変換を許可 (SQLAlchemy ORMとの連携用)
        from_attributes = True


