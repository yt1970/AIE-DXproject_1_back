from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import LectureCategory, LectureInfo

router = APIRouter()

VALID_SORT_BY = {"course_name", "academic_year", "period"}
VALID_SORT_ORDER = {"asc", "desc"}


@router.get("/courses", response_model=List[LectureInfo])
def list_courses(
    db: Session = Depends(get_db),
    name: Optional[str] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    category: Optional[LectureCategory] = None,
    sort_by: str = "course_name",
    sort_order: str = "asc",
) -> List[LectureInfo]:
    """
    DBに存在する講義の [講義名, 年度, 期間] を返す。
    """
    if sort_by not in VALID_SORT_BY:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by parameter. Must be one of: {', '.join(VALID_SORT_BY)}",
        )
    sort_order_lower = sort_order.lower()
    if sort_order_lower not in VALID_SORT_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_order parameter. Must be one of: {', '.join(VALID_SORT_ORDER)}",
        )

    # 空文字列をNoneに正規化
    name = name.strip() if name else None
    period = period.strip() if period else None

    q = db.query(models.Lecture)

    if name:
        q = q.filter(func.lower(models.Lecture.name).like(f"%{name.lower()}%"))
    if year is not None:
        q = q.filter(models.Lecture.academic_year == year)
    if period:
        q = q.filter(func.lower(models.Lecture.term) == period.lower())
    if category:
        q = q.filter(models.Lecture.category == category.value)

    lecture_sort_map = {
        "course_name": models.Lecture.name,
        "academic_year": models.Lecture.academic_year,
        "period": models.Lecture.term,
    }
    sort_col = lecture_sort_map[sort_by]
    sort_exp = sort_col.desc() if sort_order_lower == "desc" else sort_col.asc()

    lectures = q.order_by(sort_exp).all()

    return [
        LectureInfo(
            course_name=lec.name,
            academic_year=(
                str(lec.academic_year) if lec.academic_year is not None else None
            ),
            period=lec.term,
        )
        for lec in lectures
    ]
