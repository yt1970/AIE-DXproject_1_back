from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.course import LectureDetailResponse, ScoreDistributionSchema

router = APIRouter()


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()












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
        updated_at=lec.updated_at,
        score_distributions=[ScoreDistributionSchema.model_validate(d) for d in distributions],
    )

from app.schemas.analysis import (
    AverageScoreItem,
    CommentCategory,
    CommentItem,
    QuestionType,
    RatingDistribution,
    ScoreDistributions,
    Sentiment,
    SessionAnalysisResponse,
    SessionLectureInfo,
    SessionNPS,
)


@router.get("/lectures/{lecture_id}/analysis", response_model=SessionAnalysisResponse)
def get_lecture_analysis(
    lecture_id: int,
    batch_type: str = Query(..., description="preliminary/confirmed"),
    student_attribute: str = Query("all", description="受講生属性フィルタ"),
    db: Session = Depends(get_db),
) -> SessionAnalysisResponse:
    """
    特定の講義回の詳細分析データを取得する。
    """
    lec = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lec:
        raise HTTPException(status_code=404, detail="Lecture not found")

    # Find the relevant batch
    batch = (
        db.query(models.SurveyBatch)
        .filter(
            models.SurveyBatch.lecture_id == lecture_id,
            models.SurveyBatch.batch_type == batch_type
        )
        .order_by(models.SurveyBatch.uploaded_at.desc())
        .first()
    )

    if not batch:
        # Return empty/default response if no batch found
        # Or raise 404? API def doesn't specify behavior if no data.
        # Let's return a basic structure with 0 counts.
        return SessionAnalysisResponse(
            lecture_info=SessionLectureInfo(
                lecture_id=lec.id,
                session=lec.session,
                lecture_date=str(lec.lecture_on),
                instructor_name=lec.instructor_name,
                description=lec.description,
                response_count=0
            ),
            nps=SessionNPS(
                score=0.0, promoters_count=0, promoters_percentage=0.0,
                neutrals_count=0, neutrals_percentage=0.0,
                detractors_count=0, detractors_percentage=0.0
            ),
            average_scores=[],
            score_distributions=ScoreDistributions(
                overall_satisfaction=[], learning_amount=[], comprehension=[],
                operations=[], instructor_satisfaction=[], time_management=[],
                question_handling=[], speaking_style=[], preparation=[],
                motivation=[], future_application=[]
            ),
            important_comments=[],
            comments=[]
        )

    # Fetch Summary
    summary = (
        db.query(models.SurveySummary)
        .filter(
            models.SurveySummary.survey_batch_id == batch.id,
            models.SurveySummary.student_attribute == student_attribute
        )
        .first()
    )

    # Fetch Score Distributions
    dists = (
        db.query(models.ScoreDistribution)
        .filter(
            models.ScoreDistribution.survey_batch_id == batch.id,
            models.ScoreDistribution.student_attribute == student_attribute
        )
        .all()
    )
    
    # Map distributions
    dist_map = defaultdict(list)
    for d in dists:
        dist_map[d.question_key].append(RatingDistribution(rating=d.score_value, count=d.count))

    # Fetch Comments (filtering by attribute is complex if not stored in comment summary, 
    # but here we fetch raw comments or summaries? API says "comments".
    # Assuming we fetch raw comments for the list)
    # Note: ResponseComment has no direct attribute column, it's on SurveyResponse.
    
    q_comments = (
        db.query(models.ResponseComment, models.SurveyResponse)
        .join(models.SurveyResponse, models.ResponseComment.response_id == models.SurveyResponse.id)
        .filter(models.SurveyResponse.survey_batch_id == batch.id)
    )
    if student_attribute != 'all':
        q_comments = q_comments.filter(models.SurveyResponse.student_attribute == student_attribute)
        
    raw_comments = q_comments.all()
    
    comment_items = []
    important_items = []
    
    for c, r in raw_comments:


        item = CommentItem(
            id=str(c.id),
            text=c.comment_text,
            sentiment=c.llm_sentiment_type,
            category=c.llm_category,
            priority=c.llm_priority,
            fix_difficulty=c.llm_fix_difficulty,
            question_type=c.question_type,
        )
        comment_items.append(item)
        if c.llm_priority == "high":
            important_items.append(item)

    # Calculate NPS percentages
    total_nps_responses = summary.response_count if summary else 0
    promoters_pct = 0.0
    neutrals_pct = 0.0
    detractors_pct = 0.0
    
    if total_nps_responses > 0 and summary:
        promoters_pct = (summary.promoter_count / total_nps_responses) * 100.0
        neutrals_pct = (summary.passive_count / total_nps_responses) * 100.0
        detractors_pct = (summary.detractor_count / total_nps_responses) * 100.0

    # Construct Response
    return SessionAnalysisResponse(
        lecture_info=SessionLectureInfo(
            lecture_id=lec.id,
            session=lec.session,
            lecture_date=str(lec.lecture_on),
            instructor_name=lec.instructor_name,
            description=lec.description,
            response_count=summary.response_count if summary else 0
        ),
        nps=SessionNPS(
            score=float(summary.nps) if summary and summary.nps is not None else 0.0,
            promoters_count=summary.promoter_count if summary else 0,
            promoters_percentage=round(promoters_pct, 1),
            neutrals_count=summary.passive_count if summary else 0,
            neutrals_percentage=round(neutrals_pct, 1),
            detractors_count=summary.detractor_count if summary else 0,
            detractors_percentage=round(detractors_pct, 1)
        ),
        average_scores=[
            AverageScoreItem(category="総合満足度", category_key="overall_satisfaction", score=float(summary.avg_satisfaction_overall or 0), full_mark=5),
            AverageScoreItem(category="学習量", category_key="learning_amount", score=float(summary.avg_content_volume or 0), full_mark=5),
            AverageScoreItem(category="理解度", category_key="comprehension", score=float(summary.avg_content_understanding or 0), full_mark=5),
            AverageScoreItem(category="運営", category_key="operations", score=float(summary.avg_content_announcement or 0), full_mark=5),
            AverageScoreItem(category="講師満足度", category_key="instructor_satisfaction", score=float(summary.avg_instructor_overall or 0), full_mark=5),
            AverageScoreItem(category="時間使い方", category_key="time_management", score=float(summary.avg_instructor_time or 0), full_mark=5),
            AverageScoreItem(category="質問対応", category_key="question_handling", score=float(summary.avg_instructor_qa or 0), full_mark=5),
            AverageScoreItem(category="話し方", category_key="speaking_style", score=float(summary.avg_instructor_speaking or 0), full_mark=5),
            AverageScoreItem(category="予習", category_key="preparation", score=float(summary.avg_self_preparation or 0), full_mark=5),
            AverageScoreItem(category="意欲", category_key="motivation", score=float(summary.avg_self_motivation or 0), full_mark=5),
            AverageScoreItem(category="今後活用", category_key="future_application", score=float(summary.avg_self_future or 0), full_mark=5),
        ] if summary else [],
        score_distributions=ScoreDistributions(
            overall_satisfaction=dist_map.get("score_satisfaction_overall", []),
            learning_amount=dist_map.get("score_content_volume", []),
            comprehension=dist_map.get("score_content_understanding", []),
            operations=dist_map.get("score_content_announcement", []),
            instructor_satisfaction=dist_map.get("score_instructor_overall", []),
            time_management=dist_map.get("score_instructor_time", []),
            question_handling=dist_map.get("score_instructor_qa", []),
            speaking_style=dist_map.get("score_instructor_speaking", []),
            preparation=dist_map.get("score_self_preparation", []),
            motivation=dist_map.get("score_self_motivation", []),
            future_application=dist_map.get("score_self_future", [])
        ),
        important_comments=important_items,
        comments=comment_items
    )
