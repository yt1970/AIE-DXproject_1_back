import enum
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    DECIMAL,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class CategoryType(str, enum.Enum):
    instructor = "instructor"
    operation = "operation"
    material = "material"
    content = "content"
    other = "other"


class SentimentType(str, enum.Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class ImportanceType(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"
    other = "other"


class RiskLevelType(str, enum.Enum):
    flag = "flag"
    safe = "safe"
    other = "other"


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    academic_year = Column(Integer, nullable=False)
    term = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    session = Column(String(50), nullable=False)
    lecture_on = Column(Date, nullable=False)
    instructor_name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    survey_batches = relationship("SurveyBatch", back_populates="lecture")

    __table_args__ = (
        UniqueConstraint(
            "academic_year",
            "term",
            "name",
            "session",
            "lecture_on",
            name="uq_lecture_composite",
        ),
    )


class SurveyBatch(Base):
    __tablename__ = "survey_batches"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False)
    batch_type = Column(String(20), nullable=False, default='preliminary')  # 'preliminary' or 'confirmed'
    zoom_participants = Column(Integer)
    recording_views = Column(Integer)
    uploaded_at = Column(DateTime, server_default=func.now())

    # Relationships
    lecture = relationship("Lecture", back_populates="survey_batches")
    survey_responses = relationship("SurveyResponse", back_populates="survey_batch")
    survey_summaries = relationship("SurveySummary", back_populates="survey_batch")
    score_distributions = relationship("ScoreDistribution", back_populates="survey_batch")
    comment_summaries = relationship("CommentSummary", back_populates="survey_batch")


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    survey_batch_id = Column(BigInteger, ForeignKey("survey_batches.id"), nullable=False)
    account_id = Column(String(255), nullable=False)
    student_attribute = Column(String(50), nullable=False)
    
    # Scores
    score_satisfaction_overall = Column(Integer, nullable=False)
    score_content_volume = Column(Integer, nullable=False)
    score_content_understanding = Column(Integer, nullable=False)
    score_content_announcement = Column(Integer, nullable=False)
    score_instructor_overall = Column(Integer, nullable=False)
    score_instructor_time = Column(Integer, nullable=False)
    score_instructor_qa = Column(Integer, nullable=False)
    score_instructor_speaking = Column(Integer, nullable=False)
    score_self_preparation = Column(Integer, nullable=False)
    score_self_motivation = Column(Integer, nullable=False)
    score_self_future = Column(Integer, nullable=False)
    score_recommend_friend = Column(Integer, nullable=False)

    # Relationships
    survey_batch = relationship("SurveyBatch", back_populates="survey_responses")
    response_comments = relationship("ResponseComment", back_populates="response")


class ResponseComment(Base):
    __tablename__ = "response_comments"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    response_id = Column(BigInteger, ForeignKey("survey_responses.id"), nullable=False)
    question_type = Column(String(50), nullable=False)
    comment_text = Column(Text, nullable=False)
    
    # LLM Analysis
    llm_sentiment_type = Column(String(20))  # positive, neutral, negative
    llm_category = Column(String(50))   # content, materials, operations, other
    llm_importance_level = Column(String(10)) # high, medium, low
    llm_is_abusive = Column(Boolean, default=False)
    is_analyzed = Column(Boolean, default=False)

    # Relationships
    response = relationship("SurveyResponse", back_populates="response_comments")


class SurveySummary(Base):
    __tablename__ = "survey_summaries"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    survey_batch_id = Column(BigInteger, ForeignKey("survey_batches.id"), nullable=False)
    student_attribute = Column(String(50), nullable=False)
    response_count = Column(Integer, nullable=False)
    
    nps = Column(DECIMAL(5, 2))
    promoter_count = Column(Integer, nullable=False, default=0)
    passive_count = Column(Integer, nullable=False, default=0)
    detractor_count = Column(Integer, nullable=False, default=0)
    
    # Averages
    avg_satisfaction_overall = Column(DECIMAL(3, 2))
    avg_content_volume = Column(DECIMAL(3, 2))
    avg_content_understanding = Column(DECIMAL(3, 2))
    avg_content_announcement = Column(DECIMAL(3, 2))
    avg_instructor_overall = Column(DECIMAL(3, 2))
    avg_instructor_time = Column(DECIMAL(3, 2))
    avg_instructor_qa = Column(DECIMAL(3, 2))
    avg_instructor_speaking = Column(DECIMAL(3, 2))
    avg_self_preparation = Column(DECIMAL(3, 2))
    avg_self_motivation = Column(DECIMAL(3, 2))
    avg_self_future = Column(DECIMAL(3, 2))
    
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    survey_batch = relationship("SurveyBatch", back_populates="survey_summaries")


class ScoreDistribution(Base):
    __tablename__ = "score_distributions"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    survey_batch_id = Column(BigInteger, ForeignKey("survey_batches.id"), nullable=False)
    student_attribute = Column(String(50), nullable=False)
    question_key = Column(String(50), nullable=False)
    score_value = Column(Integer, nullable=False)
    count = Column(Integer, nullable=False)

    # Relationships
    survey_batch = relationship("SurveyBatch", back_populates="score_distributions")


class CommentSummary(Base):
    __tablename__ = "comment_summaries"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    survey_batch_id = Column(BigInteger, ForeignKey("survey_batches.id"), nullable=False)
    student_attribute = Column(String(50), nullable=False)
    analysis_type = Column(String(20), nullable=False) # sentiment/category
    label = Column(String(50), nullable=False)
    count = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    survey_batch = relationship("SurveyBatch", back_populates="comment_summaries")

