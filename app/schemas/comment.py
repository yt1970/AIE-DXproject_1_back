from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


# (出力) ファイルアップロード成功時の応答スキーマ
class UploadResponse(BaseModel):
    success: bool
    job_id: str
    status_url: str
    message: str


# (入力) ファイルアップロード時に必要なメタデータスキーマ
class UploadRequestMetadata(BaseModel):
    # 講義の複合識別子をフロントエンドから受け取る
    course_name: str
    lecture_on: date  # 日付型
    lecture_number: int
    lecture_id: int | None = None

    # 誰がアップロードしたかの情報（任意）
    uploader_id: int | None = None


# (出力) ジョブ状態確認の応答スキーマ
class JobResult(BaseModel):
    lecture_id: int
    batch_id: int
    response_count: int


class JobError(BaseModel):
    code: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # 'queued' | 'processing' | 'completed' | 'failed'
    created_at: datetime
    result: JobResult | None = None
    error: JobError | None = None


# (出力) 分析結果（コメント一覧）のスキーマ
class CommentAnalysisSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # ユーザー情報をCommentモデルから直接取得する
    question_type: str | None = None
    priority: str | None = Field(default=None, validation_alias="llm_priority")
    fix_difficulty: str | None = Field(default=None, validation_alias="llm_fix_difficulty")
    comment_text: str

    llm_category: str | None = None
    llm_sentiment_type: str | None = None
    llm_priority: str | None = None
    # llm_fix_difficulty is already aliased above but we can keep explicit field too or just rely on above
    # response model usually uses the field name.
    # If I want `priority` in JSON, I should name field `priority`.
    llm_fix_difficulty: str | None = None
    llm_is_abusive: bool | None = None
    is_analyzed: bool | None = None

    @computed_field
    @property
    def score_satisfaction_overall(self) -> int | None:
        sr = self.response
        return sr.score_satisfaction_overall if sr else None

    @computed_field
    @property
    def score_satisfaction_content_understanding(self) -> int | None:
        sr = self.response
        return sr.score_content_understanding if sr else None

    @computed_field
    @property
    def score_satisfaction_instructor_overall(self) -> int | None:
        sr = self.response
        return sr.score_instructor_overall if sr else None

    # responseリレーションを読み込むが、JSONには出力しないフィールド
    response: Any | None = Field(default=None, exclude=True)


# (出力) 講義重複チェックの応答スキーマ
class DuplicateCheckResponse(BaseModel):
    exists: bool
    survey_batch_id: int | None = None


# (出力) アップロード削除APIの応答スキーマ
class DeleteUploadResponse(BaseModel):
    success: bool
    deleted_batch_id: int
    deleted_response_count: int
    message: str


# (入力/出力) 講義メトリクス（手動入力）
class LectureMetricsPayload(BaseModel):
    zoom_participants: int | None = None
    recording_views: int | None = None


class LectureMetricsResponse(LectureMetricsPayload):
    survey_batch_id: int
    updated_at: datetime | None = None


# (出力) 削除対象バッチ検索の応答スキーマ
class BatchSearchItem(BaseModel):
    batch_id: int
    lecture_id: int
    session: str
    lecture_date: date
    batch_type: str
    uploaded_at: datetime


class BatchSearchResponse(BaseModel):
    batches: list[BatchSearchItem]
