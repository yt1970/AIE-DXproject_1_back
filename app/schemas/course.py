from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class AnalysisType(str, Enum):
    preliminary = "preliminary"
    confirmed = "confirmed"


class SessionSummary(BaseModel):
    lecture_id: int
    session: str
    lecture_date: date
    analysis_types: List[AnalysisType]


class CourseItem(BaseModel):
    name: str
    academic_year: int
    term: str
    sessions: List[SessionSummary]


class CourseListResponse(BaseModel):
    courses: List[CourseItem]


class BatchInfo(BaseModel):
    id: int
    batch_type: AnalysisType
    zoom_participants: Optional[int] = None
    recording_views: Optional[int] = None
    uploaded_at: datetime


class LectureInfo(BaseModel):
    id: int
    session: str
    lecture_date: date
    instructor_name: str
    description: Optional[str] = None
    batches: List[BatchInfo]


class CourseDetailResponse(BaseModel):
    name: str
    academic_year: int
    term: str
    lectures: List[LectureInfo]


# --- Legacy / Internal Schemas (Keep if needed for other parts, or refactor later) ---

class LectureCategory(str, Enum):
    講義内容 = "講義内容"
    講義資料 = "講義資料"
    運営 = "運営"
    その他 = "その他"

class LectureCreate(BaseModel):
    course_name: str
    academic_year: int
    period: str
    category: Optional[LectureCategory] = None

class LectureUpdate(BaseModel):
    course_name: Optional[str] = None
    academic_year: Optional[int] = None
    period: Optional[str] = None
    category: Optional[LectureCategory] = None

class ScoreDistributionSchema(BaseModel):
    question_key: str
    score_value: int
    count: int
    student_attribute: str
    model_config = ConfigDict(from_attributes=True)

class LectureSummaryResponse(BaseModel):
    id: int
    course_name: str
    academic_year: Optional[str] = None
    period: Optional[str] = None
    term: Optional[str] = None
    name: Optional[str] = None
    session: Optional[str] = None
    instructor_name: Optional[str] = None
    lecture_on: Optional[date] = None
    model_config = ConfigDict(from_attributes=True)

class LectureDetailResponse(LectureSummaryResponse):
    description: Optional[str] = None
    updated_at: Optional[datetime] = None
    score_distributions: List[ScoreDistributionSchema] = []
    model_config = ConfigDict(from_attributes=True)
