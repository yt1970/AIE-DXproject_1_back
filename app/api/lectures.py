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
    LectureDetailResponse,
    LectureSummaryResponse,
    LectureUpdate,
    ScoreDistributionSchema,
)

router = APIRouter()


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()


@router.get("/lectures", response_model=List[LectureSummaryResponse])
def list_lectures(
    db: Session = Depends(get_db),
    name: Optional[str] = None,
    year: Optional[int] = None,
    period: Optional[str] = None,
    category: Optional[LectureCategory] = None,
    sort_by: str = "course_name",
    sort_order: str = "asc",
) -> List[LectureInfo]:
    """オプションのフィルタとソート機能付きで講義の一覧を返す。"""
    q = db.query(models.Lecture)
    if name:
        q = q.filter(func.lower(models.Lecture.name).like(f"%{name.lower()}%"))
    if year is not None:
        q = q.filter(models.Lecture.academic_year == year)
    if period:
        q = q.filter(func.lower(models.Lecture.term) == period.lower())
    if category:
        q = q.filter(models.Lecture.category == category.value)

    sort_map = {
        "course_name": models.Lecture.name,
        "academic_year": models.Lecture.academic_year,
        "period": models.Lecture.term,
    }
    sort_col = sort_map.get(sort_by, models.Lecture.name)
    sort_exp = sort_col.desc() if sort_order.lower() == "desc" else sort_col.asc()
    lectures = q.order_by(sort_exp).all()
    return [
        LectureSummaryResponse(
            id=lec.id,
            course_name=lec.name,
            academic_year=(
                str(lec.academic_year) if lec.academic_year is not None else None
            ),
            period=lec.term,
            term=lec.term,
            name=lec.name or lec.name,
            session=lec.session,
            instructor_name=lec.instructor_name,
            lecture_on=lec.lecture_on,
        )
        for lec in lectures
    ]


@router.get("/lectures/metadata")
def get_lecture_metadata(db: Session = Depends(get_db)) -> dict:
    """フォームのドロップダウン用のメタデータを返す。コース、年度、期間を含む。"""
    # 講義テーブルから取得
    courses = [
        row[0]
        for row in db.query(models.Lecture.name).distinct().all()
        if row[0]
    ]
    years = [
        row[0]
        for row in db.query(models.Lecture.academic_year).distinct().all()
        if row[0] is not None
    ]
    terms = [
        row[0] for row in db.query(models.Lecture.term).distinct().all() if row[0]
    ]

    return {"courses": courses, "years": years, "terms": terms}


@router.post("/lectures", response_model=LectureSummaryResponse)
def create_lecture(
    payload: LectureCreate, db: Session = Depends(get_db)
) -> LectureInfo:
    """講義を作成する。コース名、年度、期間の組み合わせで重複を拒否する。"""
    course_name = _normalize_text(payload.course_name)
    period = _normalize_text(payload.period)
    if not course_name or not period:
        raise HTTPException(status_code=422, detail="コース名と期間は必須です")
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
        raise HTTPException(status_code=409, detail="講義は既に存在します")

    lec = models.Lecture(
        course_name=course_name,
        academic_year=payload.academic_year,
        period=period,
        category=category.value,
    )
    db.add(lec)
    db.commit()
    db.refresh(lec)
    return LectureSummaryResponse(
        id=lec.id,
        course_name=lec.course_name,
        academic_year=str(lec.academic_year),
        period=lec.period,
        term=lec.term,
        name=lec.name or lec.course_name,
        session=lec.session,
        instructor_name=lec.instructor_name,
        lecture_on=lec.lecture_on,
    )


@router.put("/lectures/{lecture_id}", response_model=LectureSummaryResponse)
def update_lecture(
    lecture_id: int, payload: LectureUpdate, db: Session = Depends(get_db)
) -> LectureInfo:
    """講義のフィールドを更新する。更新後の重複を防止する。"""
    lec = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lec:
        raise HTTPException(status_code=404, detail="講義が見つかりません")

    # Pydantic Enumがバリデーションするため追加チェックは不要

    if payload.course_name is not None:
        lec.course_name = _normalize_text(payload.course_name) or lec.course_name
    if payload.period is not None:
        norm = _normalize_text(payload.period)
        if not norm:
            raise HTTPException(status_code=422, detail="期間は空にできません")
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
        raise HTTPException(status_code=409, detail="更新後に重複する講義が存在します")

    db.add(lec)
    db.commit()
    db.refresh(lec)
    return LectureSummaryResponse(
        id=lec.id,
        course_name=lec.course_name,
        academic_year=str(lec.academic_year),
        period=lec.period,
        term=lec.term,
        name=lec.name or lec.course_name,
        session=lec.session,
        instructor_name=lec.instructor_name,
        lecture_on=lec.lecture_on,
    )


@router.delete("/lectures/{lecture_id}")
def delete_lecture(lecture_id: int, db: Session = Depends(get_db)) -> dict:
    """講義と関連するアップロード、コメント、メトリクスを削除する。注意して使用すること。"""
    lec = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lec:
        raise HTTPException(status_code=404, detail="講義が見つかりません")
    
    batches = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.lecture_id == lecture_id)
        .all()
    )
    # 処理中のファイルがある場合は削除をブロック
    if any(b.status == "PROCESSING" for b in batches):
        raise HTTPException(
            status_code=409, detail="一部のアップロードが現在処理中です"
        )
    
    removed_comments = 0
    removed_survey_responses = 0
    
    for b in batches:
        removed_comments += (
            db.query(models.ResponseComment)
            .filter(models.ResponseComment.survey_batch_id == b.id)
            .delete(synchronize_session=False)
            or 0
        )
        removed_survey_responses += (
            db.query(models.SurveyResponse)
            .filter(models.SurveyResponse.survey_batch_id == b.id)
            .delete(synchronize_session=False)
            or 0
        )
        
        db.query(models.SurveySummary).filter(
            models.SurveySummary.survey_batch_id == b.id
        ).delete(synchronize_session=False)
        db.query(models.CommentSummary).filter(
            models.CommentSummary.survey_batch_id == b.id
        ).delete(synchronize_session=False)
        
        db.delete(b)
        
    # 最後に講義を削除
    db.query(models.Lecture).filter(models.Lecture.id == lecture_id).delete(
        synchronize_session=False
    )
    db.commit()
    return {
        "lecture_id": lecture_id,
        "deleted": True,
        "removed_batches": len(batches),
        "removed_comments": removed_comments,
        "removed_survey_responses": removed_survey_responses,
    }


@router.get("/lectures/{lecture_id}", response_model=LectureDetailResponse)
def get_lecture_detail(lecture_id: int, db: Session = Depends(get_db)) -> LectureDetailResponse:
    """講義詳細を返す（ScoreDistributionを含む）。"""
    lec = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lec:
        raise HTTPException(status_code=404, detail="講義が見つかりません")

    distributions = (
        db.query(models.ScoreDistribution)
        .join(models.SurveyBatch, models.ScoreDistribution.survey_batch_id == models.SurveyBatch.id)
        .filter(models.SurveyBatch.lecture_id == lecture_id)
        .all()
    )

    return LectureDetailResponse(
        id=lec.id,
        course_name=lec.course_name,
        academic_year=str(lec.academic_year) if lec.academic_year is not None else None,
        period=lec.period,
        term=lec.term,
        name=lec.name or lec.course_name,
        session=lec.session,
        instructor_name=lec.instructor_name,
        lecture_on=lec.lecture_on,
        description=lec.description,
        created_at=lec.created_at,
        updated_at=lec.updated_at,
        score_distributions=[ScoreDistributionSchema.model_validate(d) for d in distributions],
    )
