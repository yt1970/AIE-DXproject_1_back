from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class AnalysisType(str, Enum):
    preliminary = "preliminary"
    confirmed = "confirmed"


class SessionSummary(BaseModel):
    lecture_id: int
    session: str
    lecture_date: date
    analysis_types: list[AnalysisType]


class CourseItem(BaseModel):
    name: str
    academic_year: int
    term: str
    sessions: list[SessionSummary]


class CourseListResponse(BaseModel):
    courses: list[CourseItem]


class BatchInfo(BaseModel):
    id: int
    batch_type: AnalysisType
    zoom_participants: int | None = None
    recording_views: int | None = None
    uploaded_at: datetime


class LectureInfo(BaseModel):
    id: int
    session: str
    lecture_date: date
    instructor_name: str
    description: str | None = None
    batches: list[BatchInfo]


class CourseDetailResponse(BaseModel):
    name: str
    academic_year: int
    term: str
    lectures: list[LectureInfo]


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
    category: LectureCategory | None = None


class LectureUpdate(BaseModel):
    course_name: str | None = None
    academic_year: int | None = None
    period: str | None = None
    category: LectureCategory | None = None


class ScoreDistributionSchema(BaseModel):
    question_key: str
    score_value: int
    count: int
    student_attribute: str
    model_config = ConfigDict(from_attributes=True)


class LectureSummaryResponse(BaseModel):
    id: int
    course_name: str
    academic_year: str | None = None
    period: str | None = None
    term: str | None = None
    name: str | None = None
    session: str | None = None
    instructor_name: str | None = None
    lecture_on: date | None = None
    model_config = ConfigDict(from_attributes=True)


class LectureDetailResponse(LectureSummaryResponse):
    description: str | None = None
    updated_at: datetime | None = None
    score_distributions: list[ScoreDistributionSchema] = []
    model_config = ConfigDict(from_attributes=True)
