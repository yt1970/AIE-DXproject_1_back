from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import LectureInfo


router = APIRouter()


@router.get("/courses", response_model=List[LectureInfo])
def list_courses(db: Session = Depends(get_db)) -> List[LectureInfo]:
    """
    DBに存在する講義の [講義名, 年度, 期間] を返す。
    優先: lecture テーブル / フォールバック: uploaded_file から推定。
    """
    lectures = db.query(models.Lecture).order_by(models.Lecture.course_name.asc()).all()
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


