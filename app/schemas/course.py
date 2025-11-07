from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class LectureInfo(BaseModel):
    course_name: str
    academic_year: Optional[str] = None
    period: Optional[str] = None


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


