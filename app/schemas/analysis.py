from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

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
    description: Optional[str] = None


# --- Trends Response ---


class ResponseTrendItem(BaseModel):
    session: str
    response_count: int
    retention_rate: float
    breakdown: Optional[Dict[str, int]] = None


class ParticipationTrendItem(BaseModel):
    session: str
    zoom_participants: Optional[int] = None
    recording_views: Optional[int] = None


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
    scores: Dict[str, float]


class OverallAverages(BaseModel):
    overall: Dict[str, object]  # {label: str, items: List[ScoreItem]}
    content: Dict[str, object]
    instructor: Dict[str, object]
    self_evaluation: Dict[str, object]


class SentimentSummaryItem(BaseModel):
    sentiment: Sentiment
    count: int
    percentage: float


class CategorySummaryItem(BaseModel):
    category: CommentCategory
    count: int


class OverallTrendsResponse(BaseModel):
    lecture_info: List[LectureInfoItem]
    response_trends: List[ResponseTrendItem]
    participation_trends: List[ParticipationTrendItem]
    nps_summary: NPSSummary
    nps_trends: List[NPSTrendItem]
    score_trends: List[ScoreTrendItem]
    overall_averages: OverallAverages
    sentiment_summary: List[SentimentSummaryItem]
    category_summary: List[CategorySummaryItem]


# --- Comparison Response ---


class YearMetrics(BaseModel):
    academic_year: int
    term: str
    total_responses: int
    session_count: int
    average_nps: float
    average_scores: Dict[str, float]


class ScoreComparisonItem(BaseModel):
    category: str
    category_key: str
    current_score: float
    comparison_score: float
    difference: float


class YearComparisonResponse(BaseModel):
    current: YearMetrics
    comparison: YearMetrics
    nps_trends: Dict[str, List[NPSTrendItem]]  # {current: [], comparison: []}
    score_comparison: List[ScoreComparisonItem]


# --- Lecture Analysis Response ---


class SessionLectureInfo(BaseModel):
    lecture_id: int
    session: str
    lecture_date: str
    instructor_name: str
    description: Optional[str] = None
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
    overall_satisfaction: List[RatingDistribution]
    learning_amount: List[RatingDistribution]
    comprehension: List[RatingDistribution]
    operations: List[RatingDistribution]
    instructor_satisfaction: List[RatingDistribution]
    time_management: List[RatingDistribution]
    question_handling: List[RatingDistribution]
    speaking_style: List[RatingDistribution]
    preparation: List[RatingDistribution]
    motivation: List[RatingDistribution]
    future_application: List[RatingDistribution]


class CommentItem(BaseModel):
    id: str
    text: str
    sentiment: Optional[Sentiment] = None
    category: Optional[CommentCategory] = None
    priority: Optional[str] = None
    fix_difficulty: Optional[str] = None
    risk_level: Optional[str] = None
    question_type: QuestionType


class SessionAnalysisResponse(BaseModel):
    lecture_info: SessionLectureInfo
    nps: SessionNPS
    average_scores: List[AverageScoreItem]
    score_distributions: ScoreDistributions
    fix_difficulty: Dict[str, int]
    priority_comments: List[CommentItem]
    comments: List[CommentItem]
