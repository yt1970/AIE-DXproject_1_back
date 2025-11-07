from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LectureInfo(BaseModel):
    course_name: str
    academic_year: Optional[str] = None
    period: Optional[str] = None


