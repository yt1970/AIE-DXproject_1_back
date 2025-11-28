import enum

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Column,
    Date,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship, synonym

Base = declarative_base()


class SentimentType(enum.Enum):
    """感情分析結果のEnum型。"""

    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class ImportanceType(enum.Enum):
    """重要度のEnum型。"""

    high = "high"
    medium = "medium"
    low = "low"
    other = "other"


class RiskLevelType(enum.Enum):
    """リスクレベルのEnum型。"""

    flag = "Flag"
    safe = "Safe"
    other = "Other"


class CategoryType(enum.Enum):
    """カテゴリのEnum型。"""

    instructor = "講師"
    content = "講義内容"
    material = "講義資料"
    operation = "運営"
    other = "その他"


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    # 主キーとしてのサロゲートキー
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 講義の複合識別子（複合ユニークキーで整合性を保証）
    course_name = Column(String(255), nullable=False)
    lecture_date = Column(Date, nullable=False)
    lecture_number = Column(Integer, nullable=False)
    academic_year = Column(String(10))
    period = Column(String(100))

    # その他の属性
    status = Column(
        String(20), nullable=False
    )  # 想定ステータスはQUEUED/PROCESSING/COMPLETED/FAILED
    s3_key = Column(String(512))  # 保存先URI（local:// あるいは s3:// を想定）
    uploaded_at = Column(TIMESTAMP, nullable=False)
    original_filename = Column(String(255))
    content_type = Column(String(100))
    total_rows = Column(Integer)
    processed_rows = Column(Integer)
    task_id = Column(String(255))
    lecture_id = Column(Integer, ForeignKey("lectures.id"))
    processing_started_at = Column(TIMESTAMP)
    processing_completed_at = Column(TIMESTAMP)
    error_message = Column(Text)
    finalized_at = Column(TIMESTAMP)

    # 複合ユニーク制約の定義 (これで重複登録を防ぐ)
    __table_args__ = (
        UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_course_lecture_instance",
        ),
    )

    # リレーション定義
    survey_batch = relationship(
        "SurveyBatch", uselist=False, back_populates="uploaded_file"
    )
    survey_responses = relationship("SurveyResponse", back_populates="uploaded_file")
    response_comments = relationship("ResponseComment", back_populates="uploaded_file")
    metrics = relationship(
        "LectureMetrics", uselist=False, back_populates="uploaded_file"
    )

    @property
    def comments(self):
        # 既存コード経路との互換性のための名称
        return self.response_comments


class SurveyBatch(Base):
    __tablename__ = "survey_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uploaded_file_id = Column(
        Integer, ForeignKey("uploaded_files.id"), nullable=False, unique=True
    )
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=True)
    course_name = Column(String(255), nullable=False)
    lecture_date = Column(Date, nullable=False)
    lecture_number = Column(Integer, nullable=False)
    academic_year = Column(String(10))
    period = Column(String(100))

    batch_type = Column(String(20), nullable=False, server_default="preliminary")
    zoom_participants = Column(Integer)
    recording_views = Column(Integer)
    status = Column(String(20), nullable=False)
    uploaded_at = Column(TIMESTAMP, nullable=False)
    processing_started_at = Column(TIMESTAMP)
    processing_completed_at = Column(TIMESTAMP)
    finalized_at = Column(TIMESTAMP)
    error_message = Column(Text)
    total_responses = Column(Integer)
    total_comments = Column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_survey_batch_identity",
        ),
    )

    uploaded_file = relationship("UploadedFile", back_populates="survey_batch")
    survey_responses = relationship("SurveyResponse", back_populates="survey_batch")
    response_comments = relationship("ResponseComment", back_populates="survey_batch")
    survey_summary = relationship(
        "SurveySummary", uselist=False, back_populates="survey_batch"
    )
    comment_summary = relationship("CommentSummary", back_populates="survey_batch")


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uploaded_file_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=False)
    survey_batch_id = Column(
        Integer,
        ForeignKey("survey_batches.id"),
        nullable=True,
        index=True,
    )
    row_index = Column(Integer)

    # ユーザー情報
    account_id = Column(String(255), index=True)
    account_name = Column(String(255))

    # 数値評価データ
    score_satisfaction_overall = Column(Integer)
    score_satisfaction_content_volume = Column(Integer)
    score_satisfaction_content_understanding = Column(Integer)
    score_satisfaction_content_announcement = Column(Integer)
    score_satisfaction_instructor_overall = Column(Integer)
    score_satisfaction_instructor_efficiency = Column(Integer)
    score_satisfaction_instructor_response = Column(Integer)
    score_satisfaction_instructor_clarity = Column(Integer)
    score_self_preparation = Column(Integer)
    score_self_motivation = Column(Integer)
    score_self_applicability = Column(Integer)
    score_instructor_time = Column(Integer)
    score_instructor_qa = Column(Integer)
    score_instructor_speaking = Column(Integer)
    score_self_future = Column(Integer)
    score_recommend_friend = Column(Integer)
    student_attribute = Column(String(50), nullable=False)

    # リレーション定義
    uploaded_file = relationship("UploadedFile", back_populates="survey_responses")
    survey_batch = relationship("SurveyBatch", back_populates="survey_responses")


class ResponseComment(Base):
    __tablename__ = "response_comments"

    # 主キーとして単一レコードID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 外部キーで対象ファイルと受講生を参照
    uploaded_file_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=True)
    survey_batch_id = Column(
        Integer, ForeignKey("survey_batches.id"), nullable=True, index=True
    )
    survey_response_id = Column(
        Integer, ForeignKey("survey_responses.id"), nullable=True
    )

    # ユーザー情報と質問事項
    account_id = Column(String(255), index=True)
    account_name = Column(String(255))
    question_type = Column(String(50), nullable=False)
    question_text = Column(Text)

    # 生の自由記述コメント（LLM処理前）
    comment_text = Column(Text, nullable=False)
    # LLM分析結果
    llm_category = Column(String(50))
    llm_sentiment = Column(String(20))
    llm_summary = Column(Text)
    llm_importance_level = Column(String(20))
    llm_importance_score = Column(Float)
    llm_risk_level = Column(String(20))
    llm_is_abusive = Column(Boolean)
    is_analyzed = Column(Boolean)
    processed_at = Column(TIMESTAMP)  # LLM処理完了日時
    analysis_version = Column(String(20))  # 'preliminary' or 'final'
    is_important = Column(Integer)

    # リレーションの定義
    uploaded_file = relationship("UploadedFile", back_populates="response_comments")
    survey_batch = relationship("SurveyBatch", back_populates="response_comments")
    survey_response = relationship(
        "SurveyResponse", foreign_keys=[survey_response_id], backref="comments"
    )


class LectureMetrics(Base):
    __tablename__ = "lecture_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uploaded_file_id = Column(
        Integer, ForeignKey("uploaded_files.id"), nullable=False, unique=True
    )

    zoom_participants = Column(Integer)
    recording_views = Column(Integer)
    updated_at = Column(TIMESTAMP)

    uploaded_file = relationship("UploadedFile", back_populates="metrics")


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_name = Column(String(255), nullable=False)
    academic_year = Column(Integer)
    period = Column(String(100), nullable=False)  # 任意の書式の期間文字列
    term = Column(String(50))  # 新設計の期間カラム
    name = Column(String(255))  # 新設計の講座名
    session = Column(String(50))  # 講義回（例: 第1回）
    lecture_date = Column(Date)
    instructor_name = Column(String(255))
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    category = Column(String(20))  # 講義内容/講義資料/運営/その他

    __table_args__ = (
        UniqueConstraint(
            "name",
            "academic_year",
            "term",
            "session",
            "lecture_date",
            name="uq_lecture_identity",
        ),
    )


class ScoreDistribution(Base):
    __tablename__ = "score_distributions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    survey_batch_id = Column(Integer, ForeignKey("survey_batches.id"), nullable=False)
    student_attribute = Column(String(50), nullable=False)
    question_key = Column(String(50), nullable=False)
    score_value = Column(Integer, nullable=False)
    count = Column(Integer, nullable=False)

    survey_batch = relationship("SurveyBatch")

    __table_args__ = (
        UniqueConstraint(
            "survey_batch_id",
            "student_attribute",
            "question_key",
            "score_value",
            name="uq_score_distribution_entry",
        ),
    )


class SurveySummary(Base):
    __tablename__ = "survey_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    survey_batch_id = Column(Integer, ForeignKey("survey_batches.id"), nullable=False)
    analysis_version = Column(String(20), nullable=False, default="preliminary")
    student_attribute = Column(String(50))

    # 平均スコア
    score_overall_satisfaction = Column(Float)
    score_content_volume = Column(Float)
    score_content_understanding = Column(Float)
    score_content_announcement = Column(Float)
    score_instructor_overall = Column(Float)
    score_instructor_time = Column(Float)
    score_instructor_qa = Column(Float)
    score_instructor_speaking = Column(Float)
    score_self_preparation = Column(Float)
    score_self_motivation = Column(Float)
    score_self_future = Column(Float)

    # NPS関連指標
    nps_score = Column(Float)
    nps_promoters = Column(Integer)
    nps_passives = Column(Integer)
    nps_detractors = Column(Integer)
    nps_total = Column(Integer)

    response_count = Column(Integer)
    comments_count = Column(Integer)
    important_comments_count = Column(Integer)
    updated_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.now())

    survey_batch = relationship("SurveyBatch", back_populates="survey_summary")

    __table_args__ = (
        UniqueConstraint(
            "survey_batch_id",
            "analysis_version",
            "student_attribute",
            name="uq_survey_summary_batch_version",
        ),
    )


class CommentSummary(Base):
    __tablename__ = "comment_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    survey_batch_id = Column(Integer, ForeignKey("survey_batches.id"), nullable=False)
    analysis_version = Column(String(20), nullable=False, default="preliminary")
    student_attribute = Column(String(50), nullable=False, default="ALL")
    analysis_type = Column(String(20), nullable=False)
    label = Column(String(50), nullable=False)
    count = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    survey_batch = relationship("SurveyBatch", back_populates="comment_summary")

    __table_args__ = (
        UniqueConstraint(
            "survey_batch_id",
            "analysis_version",
            "student_attribute",
            "analysis_type",
            "label",
            name="uq_comment_summary_entry",
        ),
    )


# 互換性維持のための別名
Comment = ResponseComment
