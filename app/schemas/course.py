from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class LectureInfo(BaseModel):
    course_name: str
    academic_year: Optional[str] = None
    period: Optional[str] = None
    term: Optional[str] = None
    name: Optional[str] = None
    session: Optional[str] = None
    instructor_name: Optional[str] = None
    lecture_on: Optional[date] = None


class LectureCreate(BaseModel):
    course_name: str
    academic_year: int
    period: str
    category: Optional["LectureCategory"] = None  # 講義内容/講義資料/運営/その他


class LectureUpdate(BaseModel):
    course_name: Optional[str] = None
    academic_year: Optional[int] = None
    period: Optional[str] = None
    category: Optional["LectureCategory"] = None


class LectureCategory(str, Enum):
    講義内容 = "講義内容"
    講義資料 = "講義資料"
    運営 = "運営"
    その他 = "その他"


class ScoreDistributionSchema(BaseModel):
    question_key: str
    score_value: int
    count: int
    student_attribute: str

    model_config = ConfigDict(from_attributes=True)


class LectureSummaryResponse(LectureInfo):
    id: int

    model_config = ConfigDict(from_attributes=True)


class LectureDetailResponse(LectureSummaryResponse):
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    score_distributions: List[ScoreDistributionSchema] = []

    model_config = ConfigDict(from_attributes=True)
