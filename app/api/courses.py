from typing import List, Optional, Dict
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import (
    CourseListResponse,
    CourseItem,
    SessionSummary,
    CourseDetailResponse,
    LectureInfo,
    BatchInfo,
    AnalysisType,
)

router = APIRouter()

@router.get("/courses", response_model=CourseListResponse)
def list_courses(
    name: Optional[str] = None,
    academic_year: Optional[int] = None,
    term: Optional[str] = None,
    db: Session = Depends(get_db),
) -> CourseListResponse:
    """
    講座一覧を取得する。LECTURESテーブルをname, academic_year, termでグループ化して返します。
    """
    q = db.query(models.Lecture)

    if name:
        q = q.filter(models.Lecture.name.contains(name))
    if academic_year is not None:
        q = q.filter(models.Lecture.academic_year == academic_year)
    if term:
        q = q.filter(models.Lecture.term.contains(term))

    # Eager load batches to avoid N+1
    # q = q.options(joinedload(models.Lecture.survey_batches)) # If needed
    
    lectures = q.all()

    # Group by (name, academic_year, term)
    grouped: Dict[tuple, List[models.Lecture]] = defaultdict(list)
    for lec in lectures:
        key = (lec.name, lec.academic_year, lec.term)
        grouped[key].append(lec)

    course_items: List[CourseItem] = []
    
    for (c_name, c_year, c_term), lecs in grouped.items():
        # Sort lectures by date or session if needed
        lecs.sort(key=lambda x: x.lecture_on)
        
        sessions: List[SessionSummary] = []
        for lec in lecs:
            # Determine available analysis types from batches
            types = set()
            for batch in lec.survey_batches:
                if batch.batch_type == 'preliminary':
                    types.add(AnalysisType.preliminary)
                elif batch.batch_type == 'confirmed':
                    types.add(AnalysisType.confirmed)
            
            sessions.append(SessionSummary(
                lecture_id=lec.id,
                session=lec.session,
                lecture_date=lec.lecture_on,
                analysis_types=list(types)
            ))

        course_items.append(CourseItem(
            name=c_name,
            academic_year=c_year,
            term=c_term,
            sessions=sessions
        ))

    course_items.sort(key=lambda x: (-x.academic_year, x.name))
    return CourseListResponse(courses=course_items)


@router.get("/courses/detail", response_model=CourseDetailResponse)
def get_course_detail(
    name: str = Query(..., description="講座名"),
    academic_year: int = Query(..., description="年度"),
    term: str = Query(..., description="期間"),
    db: Session = Depends(get_db),
) -> CourseDetailResponse:
    """
    特定の講座（講座名・年度・期間の組み合わせ）の詳細情報を取得する。
    """
    lectures = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.name == name,
            models.Lecture.academic_year == academic_year,
            models.Lecture.term == term,
        )
        .order_by(models.Lecture.lecture_on)
        .all()
    )

    if not lectures:
        raise HTTPException(status_code=404, detail="Course not found")

    lecture_infos: List[LectureInfo] = []
    for lec in lectures:
        batches: List[BatchInfo] = []
        for b in lec.survey_batches:
            # Map string to Enum safely
            try:
                b_type = AnalysisType(b.batch_type)
            except ValueError:
                continue # Skip invalid types

            batches.append(BatchInfo(
                id=b.id,
                batch_type=b_type,
                zoom_participants=b.zoom_participants,
                recording_views=b.recording_views,
                uploaded_at=b.uploaded_at
            ))
        
        lecture_infos.append(LectureInfo(
            id=lec.id,
            session=lec.session,
            lecture_date=lec.lecture_on,
            instructor_name=lec.instructor_name,
            description=lec.description,
            batches=batches
        ))

    return CourseDetailResponse(
        name=name,
        academic_year=academic_year,
        term=term,
        lectures=lecture_infos
    )
