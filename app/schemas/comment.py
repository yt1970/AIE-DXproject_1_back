from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


# (出力) ファイルアップロード成功時の応答スキーマ
class UploadResponse(BaseModel):
    survey_batch_id: int
    status_url: str
    message: str


# (入力) ファイルアップロード時に必要なメタデータスキーマ
class UploadRequestMetadata(BaseModel):
    # 講義の複合識別子をフロントエンドから受け取る
    course_name: str
    lecture_on: date  # 日付型
    lecture_number: int
    lecture_id: Optional[int] = None

    # 誰がアップロードしたかの情報（任意）
    uploader_id: Optional[int] = None


# (出力) ステータス確認時の応答スキーマ
class AnalysisStatusResponse(BaseModel):
    survey_batch_id: int
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
    model_config = ConfigDict(from_attributes=True)

    # ユーザー情報をCommentモデルから直接取得する
    question_type: Optional[str] = None
    comment_text: str

    llm_category: Optional[str] = None
    llm_sentiment_type: Optional[str] = None
    llm_importance_level: Optional[str] = None
    llm_is_abusive: Optional[bool] = None
    is_analyzed: Optional[bool] = None

    # @computed_fieldを使って、ネストされたリレーションから値を取得する
    @computed_field
    @property
    def score_satisfaction_overall(self) -> Optional[int]:
        sr = self.response
        return sr.score_satisfaction_overall if sr else None

    @computed_field
    @property
    def score_satisfaction_content_understanding(self) -> Optional[int]:
        sr = self.response
        return sr.score_content_understanding if sr else None

    @computed_field
    @property
    def score_satisfaction_instructor_overall(self) -> Optional[int]:
        sr = self.response
        return sr.score_instructor_overall if sr else None

    # responseリレーションを読み込むが、JSONには出力しないフィールド
    response: Optional[Any] = Field(default=None, exclude=True)


# (出力) 講義重複チェックの応答スキーマ
class DuplicateCheckResponse(BaseModel):
    exists: bool
    survey_batch_id: Optional[int] = None


# (出力) アップロード削除APIの応答スキーマ
class DeleteUploadResponse(BaseModel):
    survey_batch_id: int
    deleted: bool
    removed_comments: int
    removed_survey_responses: int


# (入力/出力) 講義メトリクス（手動入力）
class LectureMetricsPayload(BaseModel):
    zoom_participants: Optional[int] = None
    recording_views: Optional[int] = None


class LectureMetricsResponse(LectureMetricsPayload):
    survey_batch_id: int
    updated_at: Optional[datetime] = None
