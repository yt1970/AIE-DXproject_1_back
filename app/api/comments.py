import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, contains_eager

from app.db import models
from app.db.session import get_db
from app.schemas.comment import CommentAnalysisSchema

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/courses/{course_name}/comments", response_model=List[CommentAnalysisSchema]
)
def get_course_comments(
    course_name: str,
    limit: int = 100,
    skip: int = 0,
    version: str | None = None,
    db: Session = Depends(get_db),
):
    """講義名単位で最新のコメント分析結果を取得する。"""
    query = (
        db.query(models.Comment)
        .join(models.Comment.uploaded_file)
        .outerjoin(models.Comment.survey_response)
        .filter(models.UploadedFile.course_name == course_name)
        .options(
            contains_eager(models.Comment.uploaded_file),
            contains_eager(models.Comment.survey_response),
        )
    )
    if version:
        query = query.filter(models.Comment.analysis_version == version)
    comments_with_scores = (
        query.order_by(models.Comment.id.desc()).offset(skip).limit(limit).all()
    )

    if comments_with_scores:
        first_comment = comments_with_scores[0]
        logger.info("--- Fetched data from DB for API response ---")
        logger.info("First Comment object from DB: %s", first_comment.__dict__)
        if first_comment.survey_response:
            logger.info(
                "Attached SurveyResponse object: %s",
                first_comment.survey_response.__dict__,
            )
        else:
            logger.info("No SurveyResponse attached to the first comment.")

    return comments_with_scores
