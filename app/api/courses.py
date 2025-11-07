from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import LectureCategory, LectureInfo


router = APIRouter()


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
    優先: lecture テーブル / フォールバック: uploaded_file から推定。
    """
    q = db.query(models.Lecture)
    if name:
        q = q.filter(func.lower(models.Lecture.course_name).like(f"%{name.lower()}%"))
    if year is not None:
        q = q.filter(models.Lecture.academic_year == year)
    if period:
        q = q.filter(func.lower(models.Lecture.period) == period.lower())
    if category:
        q = q.filter(models.Lecture.category == category.value)

    sort_map = {
        "course_name": models.Lecture.course_name,
        "academic_year": models.Lecture.academic_year,
        "period": models.Lecture.period,
    }
    sort_col = sort_map.get(sort_by, models.Lecture.course_name)
    sort_exp = sort_col.desc() if sort_order.lower() == "desc" else sort_col.asc()

    lectures = q.order_by(sort_exp).all()
    if lectures:
        return [
            LectureInfo(
                course_name=lec.course_name,
                academic_year=(str(lec.academic_year) if lec.academic_year is not None else None),
                period=lec.period,
            )
            for lec in lectures
        ]

    rows = (
        db.query(
            models.UploadedFile.course_name,
            func.strftime("%Y", models.UploadedFile.lecture_date),
        )
        .distinct()
        .order_by(models.UploadedFile.course_name.asc())
        .all()
    )
    return [
        LectureInfo(course_name=name, academic_year=(year_str or None), period=None)
        for name, year_str in rows
    ]


