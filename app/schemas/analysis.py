from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

# --- Enums ---


class StudentAttribute(str, Enum):
    all = "all"
    student = "student"
    corporate = "corporate"
    invited = "invited"
    faculty = "faculty"
    other = "other"


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class CommentCategory(str, Enum):
    content = "content"
    materials = "materials"
    operations = "operations"
    instructor = "instructor"
    other = "other"


class QuestionType(str, Enum):
    learned = "learned"
    good_points = "good_points"
    improvements = "improvements"
    instructor_feedback = "instructor_feedback"
    future_requests = "future_requests"
    free_comment = "free_comment"


# --- Shared / Common ---


class ScoreItem(BaseModel):
    name: str
    score: float


class NPSTrendItem(BaseModel):
    session: str
    nps_score: float


class LectureInfoItem(BaseModel):
    lecture_id: int
    session: str
    lecture_date: str
    instructor_name: str
    description: str | None = None


# --- Trends Response ---


class ResponseTrendItem(BaseModel):
    session: str
    response_count: int
    retention_rate: float
    breakdown: dict[str, int] | None = None


class ParticipationTrendItem(BaseModel):
    session: str
    zoom_participants: int | None = None
    recording_views: int | None = None


class NPSSummary(BaseModel):
    score: float
    promoters_count: int
    promoters_percentage: float
    neutrals_count: int
    neutrals_percentage: float
    detractors_count: int
    detractors_percentage: float
    total_responses: int


class ScoreTrendItem(BaseModel):
    session: str
    scores: dict[str, float]


class OverallAverages(BaseModel):
    overall: dict[str, object]  # {label: str, items: List[ScoreItem]}
    content: dict[str, object]
    instructor: dict[str, object]
    self_evaluation: dict[str, object]


class SentimentSummaryItem(BaseModel):
    sentiment: Sentiment
    count: int
    percentage: float


class CategorySummaryItem(BaseModel):
    category: CommentCategory
    count: int


class OverallTrendsResponse(BaseModel):
    lecture_info: list[LectureInfoItem]
    response_trends: list[ResponseTrendItem]
    participation_trends: list[ParticipationTrendItem]
    nps_summary: NPSSummary
    nps_trends: list[NPSTrendItem]
    score_trends: list[ScoreTrendItem]
    overall_averages: OverallAverages
    sentiment_summary: list[SentimentSummaryItem]
    category_summary: list[CategorySummaryItem]


# --- Comparison Response ---


class YearMetrics(BaseModel):
    academic_year: int
    term: str
    total_responses: int
    session_count: int
    average_nps: float
    average_scores: dict[str, float]


class ScoreComparisonItem(BaseModel):
    category: str
    category_key: str
    current_score: float
    comparison_score: float
    difference: float


class YearComparisonResponse(BaseModel):
    current: YearMetrics
    comparison: YearMetrics
    nps_trends: dict[str, list[NPSTrendItem]]  # {current: [], comparison: []}
    score_comparison: list[ScoreComparisonItem]


# --- Lecture Analysis Response ---


class SessionLectureInfo(BaseModel):
    lecture_id: int
    session: str
    lecture_date: str
    instructor_name: str
    description: str | None = None
    response_count: int


class SessionNPS(BaseModel):
    score: float
    promoters_count: int
    promoters_percentage: float
    neutrals_count: int
    neutrals_percentage: float
    detractors_count: int
    detractors_percentage: float


class AverageScoreItem(BaseModel):
    category: str
    category_key: str
    score: float
    full_mark: int = 5


class RatingDistribution(BaseModel):
    rating: int
    count: int


class ScoreDistributions(BaseModel):
    overall_satisfaction: list[RatingDistribution]
    learning_amount: list[RatingDistribution]
    comprehension: list[RatingDistribution]
    operations: list[RatingDistribution]
    instructor_satisfaction: list[RatingDistribution]
    time_management: list[RatingDistribution]
    question_handling: list[RatingDistribution]
    speaking_style: list[RatingDistribution]
    preparation: list[RatingDistribution]
    motivation: list[RatingDistribution]
    future_application: list[RatingDistribution]


class CommentItem(BaseModel):
    id: str
    text: str
    sentiment: Sentiment | None = None
    category: CommentCategory | None = None
    priority: str | None = None
    fix_difficulty: str | None = None
    risk_level: str | None = None
    question_type: QuestionType


class SessionAnalysisResponse(BaseModel):
    lecture_info: SessionLectureInfo
    nps: SessionNPS
    average_scores: list[AverageScoreItem]
    score_distributions: ScoreDistributions
    fix_difficulty: dict[str, int]
    priority_comments: list[CommentItem]
    comments: list[CommentItem]
