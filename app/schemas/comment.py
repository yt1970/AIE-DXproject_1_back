from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field


# (出力) ファイルアップロード成功時の応答スキーマ
class UploadResponse(BaseModel):
    file_id: int
    status_url: str
    message: str


# (入力) ファイルアップロード時に必要なメタデータスキーマ
class UploadRequestMetadata(BaseModel):
    # 講義の複合識別子をフロントエンドから受け取る
    course_name: str
    lecture_date: date  # 日付型
    lecture_number: int

    # 誰がアップロードしたかの情報（任意）
    uploader_id: Optional[int] = None


# (出力) ステータス確認時の応答スキーマ
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


# (出力) 分析結果（コメント一覧）のスキーマ
class CommentAnalysisSchema(BaseModel):
    # ユーザー情報をCommentモデルから直接取得する
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    question_text: Optional[str] = None
    comment_text: str

    llm_category: Optional[str] = None
    llm_sentiment: Optional[str] = None
    llm_summary: Optional[str] = None
    llm_importance_level: Optional[str] = None
    llm_importance_score: Optional[float] = None
    llm_risk_level: Optional[str] = None

    # @computed_fieldを使って、ネストされたリレーションから値を取得する
    @computed_field
    @property
    def score_satisfaction_overall(self) -> Optional[int]:
        if self.survey_response:
            return self.survey_response.score_satisfaction_overall
        return None

    @computed_field
    @property
    def score_satisfaction_content_understanding(self) -> Optional[int]:
        if self.survey_response:
            return self.survey_response.score_satisfaction_content_understanding
        return None

    @computed_field
    @property
    def score_satisfaction_instructor_overall(self) -> Optional[int]:
        if self.survey_response:
            return self.survey_response.score_satisfaction_instructor_overall
        return None

    class Config:
        # DBモデルからの変換を許可 (SQLAlchemy ORMとの連携用)
        from_attributes = True

    # survey_responseリレーションを読み込むが、JSONには出力しないフィールド
    survey_response: Optional[Any] = Field(default=None, exclude=True)


# (出力) 講義重複チェックの応答スキーマ
class DuplicateCheckResponse(BaseModel):
    exists: bool
    file_id: Optional[int] = None


# (出力) アップロード削除APIの応答スキーマ
class DeleteUploadResponse(BaseModel):
    file_id: int
    deleted: bool
    removed_comments: int
    removed_survey_responses: int


# (入力/出力) 講義メトリクス（手動入力）
class LectureMetricsPayload(BaseModel):
    zoom_participants: Optional[int] = None
    recording_views: Optional[int] = None


class LectureMetricsResponse(LectureMetricsPayload):
    file_id: int
    updated_at: Optional[datetime] = None
