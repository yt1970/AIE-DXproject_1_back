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


class Comment(Base):
    __tablename__ = "comment"

    # PK: 単一レコードID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # FK (外部キー): どのファイル、どの受講生かを参照
    file_id = Column(Integer, ForeignKey("uploaded_file.file_id"), nullable=False)

    # 数値評価データ
    score_satisfaction_overall = Column(Integer)
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

    # リレーションの定義
    uploaded_file = relationship("UploadedFile", back_populates="comments")
