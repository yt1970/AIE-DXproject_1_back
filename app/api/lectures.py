from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import LectureCategory, LectureCreate, LectureInfo, LectureUpdate


router = APIRouter()


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()


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


