import enum

from sqlalchemy import (
    TIMESTAMP,
    Column,
    Date,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class SentimentType(enum.Enum):
    """感情分析結果のEnum型。"""

    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class CommentType(enum.Enum):
    """コメントのカテゴリEnum型。"""

    general = "general"
    question = "question"
    complaint = "complaint"
    praise = "praise"
    other = "other"


class UploadedFile(Base):
    __tablename__ = "uploaded_file"

    # PK: サロゲートキー
    file_id = Column(Integer, primary_key=True, autoincrement=True)

    # 講義の複合識別子（複合ユニークキーで整合性を保証）
    course_name = Column(String(255), nullable=False)
    lecture_date = Column(Date, nullable=False)
    lecture_number = Column(Integer, nullable=False)
    academic_year = Column(String(10))
    period = Column(String(100))

    # その他の属性
    status = Column(
        String(20), nullable=False
    )  # QUEUED, PROCESSING, COMPLETED, FAILED
    s3_key = Column(String(512))  # 保存先URI（local:// あるいは s3:// を想定）
    upload_timestamp = Column(TIMESTAMP, nullable=False)
    original_filename = Column(String(255))
    content_type = Column(String(100))
    total_rows = Column(Integer)
    processed_rows = Column(Integer)
    task_id = Column(String(255))
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
    comments = relationship("Comment", back_populates="uploaded_file")
    survey_responses = relationship(
        "SurveyResponse", back_populates="uploaded_file"
    )
    metrics = relationship(
        "LectureMetrics", uselist=False, back_populates="uploaded_file"
    )


class SurveyResponse(Base):
    __tablename__ = "survey_response"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("uploaded_file.file_id"), nullable=False)

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
    score_recommend_to_friend = Column(Integer)

    # リレーション定義
    uploaded_file = relationship("UploadedFile", back_populates="survey_responses")


class Comment(Base):
    __tablename__ = "comment"

    # PK: 単一レコードID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # FK (外部キー): どのファイル、どの受講生かを参照
    file_id = Column(Integer, ForeignKey("uploaded_file.file_id"), nullable=False)
    survey_response_id = Column(
        Integer, ForeignKey("survey_response.id"), nullable=True
    )
    
    # ユーザー情報と質問事項
    account_id = Column(String(255), index=True)
    account_name = Column(String(255))
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
    processed_at = Column(TIMESTAMP)  # LLM処理完了日時
    analysis_version = Column(String(20))  # 'preliminary' or 'final'

    # リレーションの定義
    uploaded_file = relationship("UploadedFile", back_populates="comments")
    survey_response = relationship(
        "SurveyResponse", foreign_keys=[survey_response_id], backref="comments"
    )


class LectureMetrics(Base):
    __tablename__ = "lecture_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(
        Integer, ForeignKey("uploaded_file.file_id"), nullable=False, unique=True
    )

    zoom_participants = Column(Integer)
    recording_views = Column(Integer)
    updated_at = Column(TIMESTAMP)

    uploaded_file = relationship("UploadedFile", back_populates="metrics")


class Lecture(Base):
    __tablename__ = "lecture"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_name = Column(String(255), nullable=False)
    academic_year = Column(Integer)
    period = Column(String(100))  # 任意の書式の期間文字列
    category = Column(String(20))  # 講義内容/講義資料/運営/その他

    __table_args__ = (
        UniqueConstraint("course_name", "academic_year", "period", name="uq_lecture_identity"),
    )
