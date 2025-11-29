import logging
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, contains_eager

from app.db import models
from app.db.session import get_db
from app.schemas.comment import CommentAnalysisSchema

router = APIRouter()
logger = logging.getLogger(__name__)


IMPORTANT_LEVELS = (
    models.ImportanceType.medium.value,
    models.ImportanceType.high.value,
)


@router.get("/courses/{course_name}/comments", response_model=List[CommentAnalysisSchema])
def get_course_comments(
    course_name: str,
    limit: int = 100,
    skip: int = 0,
    version: str | None = None,
    importance: str | None = Query(
        default=None,
        description="importance level to filter (low/medium/high/other)",
        pattern="^(low|medium|high|other)$",
    ),
    important_only: bool = Query(
        default=False,
        description="When true, only medium/high importance comments are returned",
    ),
    db: Session = Depends(get_db),
):
    """講義名単位で最新のコメント分析結果を取得する。"""
    query = (
        db.query(models.ResponseComment)
        .join(models.SurveyResponse, models.ResponseComment.response_id == models.SurveyResponse.id)
        .join(models.SurveyBatch, models.SurveyResponse.survey_batch_id == models.SurveyBatch.id)
        .join(models.Lecture, models.SurveyBatch.lecture_id == models.Lecture.id)
        .options(
            contains_eager(models.ResponseComment.response),
        )
        .filter(models.Lecture.name == course_name)
        .options(
            contains_eager(models.ResponseComment.response),
        )
    )
    if version:
        query = query.filter(models.ResponseComment.analysis_version == version)
    if importance:
        query = query.filter(models.ResponseComment.llm_importance_level == importance)
    elif important_only:
        query = query.filter(
            models.ResponseComment.llm_importance_level.in_(IMPORTANT_LEVELS)
        )
    comments_with_scores = (
        query.order_by(models.ResponseComment.id.desc()).offset(skip).limit(limit).all()
    )

    if comments_with_scores:
        first_comment = comments_with_scores[0]
        logger.info("--- Fetched data from DB for API response ---")
        logger.info("First Comment object from DB: %s", first_comment.__dict__)
        if first_comment.response:
            logger.info(
                "Attached SurveyResponse object: %s",
                first_comment.response.__dict__,
            )
        else:
            logger.info("No SurveyResponse attached to the first comment.")

    return comments_with_scores
