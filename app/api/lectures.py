from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import (
    LectureCategory,
    LectureCreate,
    LectureInfo,
    LectureUpdate,
)

router = APIRouter()


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()


@router.get("/lectures", response_model=List[LectureInfo])
def list_lectures(
    db: Session = Depends(get_db),
    name: Optional[str] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    category: Optional[LectureCategory] = None,
    sort_by: str = "course_name",
    sort_order: str = "asc",
) -> List[LectureInfo]:
    """
    講義一覧を返す（coursesエンドポイントと同等の機能をlecturesに提供）。
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
    return [
        LectureInfo(
            course_name=lec.course_name,
            academic_year=(str(lec.academic_year) if lec.academic_year is not None else None),
            period=lec.period,
        )
        for lec in lectures
    ]


@router.get("/lectures/metadata")
def get_lecture_metadata(db: Session = Depends(get_db)) -> dict:
    """
    データ追加フォーム用の選択肢データを返す。
    優先: lecture テーブル / フォールバック: uploaded_file から推定。
    """
    # From lecture table
    courses = [row[0] for row in db.query(models.Lecture.course_name).distinct().all() if row[0]]
    years = [row[0] for row in db.query(models.Lecture.academic_year).distinct().all() if row[0] is not None]
    terms = [row[0] for row in db.query(models.Lecture.period).distinct().all() if row[0]]

    if not courses:
        courses = [row[0] for row in db.query(models.UploadedFile.course_name).distinct().all() if row[0]]
    if not years:
        years = [
            row[0]
            for row in db.query(func.strftime("%Y", models.UploadedFile.lecture_date))
            .distinct()
            .all()
            if row[0]
        ]
        years = [int(y) for y in years if y.isdigit()]
    # terms fallback cannot be derived from uploaded_file; leave as empty if missing

    return {"courses": courses, "years": years, "terms": terms}


@router.post("/lectures", response_model=LectureInfo)
def create_lecture(payload: LectureCreate, db: Session = Depends(get_db)) -> LectureInfo:
    course_name = _normalize_text(payload.course_name)
    period = _normalize_text(payload.period)
    if not course_name or not period:
        raise HTTPException(status_code=422, detail="course_name and period are required")
    # Pydantic Enumがバリデーションするため、ここでは変換のみ
    category = payload.category or LectureCategory.その他

    exists = (
        db.query(models.Lecture)
        .filter(
            func.lower(models.Lecture.course_name) == func.lower(course_name),
            models.Lecture.academic_year == payload.academic_year,
            func.lower(models.Lecture.period) == func.lower(period),
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Lecture already exists")

    lec = models.Lecture(
        course_name=course_name,
        academic_year=payload.academic_year,
        period=period,
        category=category.value,
    )
    db.add(lec)
    db.commit()
    db.refresh(lec)
    return LectureInfo(
        course_name=lec.course_name, academic_year=str(lec.academic_year), period=lec.period
    )


@router.put("/lectures/{lecture_id}", response_model=LectureInfo)
def update_lecture(
    lecture_id: int, payload: LectureUpdate, db: Session = Depends(get_db)
) -> LectureInfo:
    lec = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lec:
        raise HTTPException(status_code=404, detail="Lecture not found")

    # Pydantic Enumがバリデーションするため追加チェックは不要

    if payload.course_name is not None:
        lec.course_name = _normalize_text(payload.course_name) or lec.course_name
    if payload.period is not None:
        norm = _normalize_text(payload.period)
        if not norm:
            raise HTTPException(status_code=422, detail="period cannot be empty")
        lec.period = norm
    if payload.academic_year is not None:
        lec.academic_year = payload.academic_year
    if payload.category is not None:
        lec.category = payload.category.value

    # 重複チェック
    dup = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.id != lecture_id,
            func.lower(models.Lecture.course_name) == func.lower(lec.course_name),
            models.Lecture.academic_year == lec.academic_year,
            func.lower(models.Lecture.period) == func.lower(lec.period),
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail="Duplicated lecture after update")

    db.add(lec)
    db.commit()
    db.refresh(lec)
    return LectureInfo(
        course_name=lec.course_name, academic_year=str(lec.academic_year), period=lec.period
    )

@router.delete("/lectures/{lecture_id}")
def delete_lecture(lecture_id: int, db: Session = Depends(get_db)) -> dict:
    lec = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lec:
        raise HTTPException(status_code=404, detail="Lecture not found")
    files = db.query(models.UploadedFile).filter(models.UploadedFile.lecture_id == lecture_id).all()
    # Block deletion if any file is processing
    if any(f.status == "PROCESSING" for f in files):
        raise HTTPException(status_code=409, detail="Some uploads are currently processing")
    # Delete related records per file
    from app.services import get_storage_client
    storage = get_storage_client()
    removed_comments = 0
    removed_survey_responses = 0
    removed_metrics = 0
    for f in files:
        # best-effort delete storage object
        try:
            if f.s3_key:
                storage.delete(uri=f.s3_key)
        except Exception:
            pass
        removed_comments += (
            db.query(models.Comment).filter(models.Comment.file_id == f.file_id).delete(synchronize_session=False) or 0
        )
        removed_survey_responses += (
            db.query(models.SurveyResponse).filter(models.SurveyResponse.file_id == f.file_id).delete(synchronize_session=False) or 0
        )
        removed_metrics += (
            db.query(models.LectureMetrics).filter(models.LectureMetrics.file_id == f.file_id).delete(synchronize_session=False) or 0
        )
        db.query(models.UploadedFile).filter(models.UploadedFile.file_id == f.file_id).delete(synchronize_session=False)
    # finally delete lecture
    db.query(models.Lecture).filter(models.Lecture.id == lecture_id).delete(synchronize_session=False)
    db.commit()
    return {
        "lecture_id": lecture_id,
        "deleted": True,
        "removed_uploads": len(files),
        "removed_comments": removed_comments,
        "removed_survey_responses": removed_survey_responses,
        "removed_metrics": removed_metrics,
    }
