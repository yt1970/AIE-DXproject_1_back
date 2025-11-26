from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional, Tuple

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.db import models

IMPORTANT_LEVELS = ("medium", "high")


def _version_filter(version: str | None):
    if version == "final":
        return models.ResponseComment.analysis_version == "final"
    if version == "preliminary":
        return or_(
            models.ResponseComment.analysis_version == "preliminary",
            models.ResponseComment.analysis_version.is_(None),
        )
    return None


def compute_and_upsert_summaries(
    db: Session,
    *,
    survey_batch: models.SurveyBatch,
    version: str = "preliminary",
    nps_scale: int = 10,
) -> Tuple[models.SurveySummary, models.CommentSummary]:
    """
    サーベイバッチの集計を計算し、SurveySummary/CommentSummaryをアップサートする。
    """
    db.flush()

    survey_summary = (
        db.query(models.SurveySummary)
        .filter(
            models.SurveySummary.survey_batch_id == survey_batch.id,
            models.SurveySummary.analysis_version == version,
        )
        .first()
    )
    if not survey_summary:
        survey_summary = models.SurveySummary(
            survey_batch_id=survey_batch.id, analysis_version=version
        )

    comment_summary = (
        db.query(models.CommentSummary)
        .filter(
            models.CommentSummary.survey_batch_id == survey_batch.id,
            models.CommentSummary.analysis_version == version,
        )
        .first()
    )
    if not comment_summary:
        comment_summary = models.CommentSummary(
            survey_batch_id=survey_batch.id, analysis_version=version
        )

    _populate_survey_summary(db, survey_summary, survey_batch.id, nps_scale)
    _populate_comment_summary(db, comment_summary, survey_batch.id, version)
    # サマリー間でカウントを揃える
    survey_summary.comments_count = comment_summary.comments_count or 0
    survey_summary.important_comments_count = comment_summary.important_comments_count or 0

    now = datetime.now(UTC)
    survey_summary.updated_at = now
    comment_summary.updated_at = now

    db.add(survey_summary)
    db.add(comment_summary)
    return survey_summary, comment_summary


def _populate_survey_summary(
    db: Session,
    summary: models.SurveySummary,
    survey_batch_id: int,
    nps_scale: int,
) -> None:
    score_fields = {
        "score_overall_satisfaction": models.SurveyResponse.score_satisfaction_overall,
        "score_content_volume": models.SurveyResponse.score_satisfaction_content_volume,
        "score_content_understanding": models.SurveyResponse.score_satisfaction_content_understanding,
        "score_content_announcement": models.SurveyResponse.score_satisfaction_content_announcement,
        "score_instructor_overall": models.SurveyResponse.score_satisfaction_instructor_overall,
        "score_instructor_time": models.SurveyResponse.score_satisfaction_instructor_efficiency,
        "score_instructor_qa": models.SurveyResponse.score_satisfaction_instructor_response,
        "score_instructor_speaking": models.SurveyResponse.score_satisfaction_instructor_clarity,
        "score_self_preparation": models.SurveyResponse.score_self_preparation,
        "score_self_motivation": models.SurveyResponse.score_self_motivation,
        "score_self_future": models.SurveyResponse.score_self_applicability,
    }

    aggregates = db.query(
        *[func.avg(col) for col in score_fields.values()],
        func.count(models.SurveyResponse.id),
    ).filter(models.SurveyResponse.survey_batch_id == survey_batch_id).one()

    for (field_name, _), value in zip(score_fields.items(), aggregates):
        setattr(summary, field_name, _maybe_round(value))

    responses_count = aggregates[-1]
    summary.responses_count = int(responses_count) if responses_count is not None else 0

    # NPSの計算
    nps_breakdown = _nps_breakdown_from_db(
        db, survey_batch_id=survey_batch_id, nps_scale=nps_scale
    )
    summary.nps_score = nps_breakdown["score"]
    summary.nps_promoters = nps_breakdown["promoters"]
    summary.nps_passives = nps_breakdown["passives"]
    summary.nps_detractors = nps_breakdown["detractors"]
    summary.nps_total = nps_breakdown["total"]

    # コメント関連のカウントは後でコメントサマリーから反映して整合を取る
    # が、Noneを避けるためデフォルト0を設定しておく
    summary.comments_count = summary.comments_count or 0
    summary.important_comments_count = summary.important_comments_count or 0


def _populate_comment_summary(
    db: Session,
    summary: models.CommentSummary,
    survey_batch_id: int,
    version: str,
) -> None:
    filters = [models.ResponseComment.survey_batch_id == survey_batch_id]
    vf = _version_filter(version)
    if vf is not None:
        filters.append(vf)

    rc = models.ResponseComment
    aggregates = (
        db.query(
            func.count(1).label("total_comments"),
            func.sum(
                case((rc.llm_sentiment == "positive", 1), else_=0)
            ).label("sentiment_positive"),
            func.sum(
                case((rc.llm_sentiment == "negative", 1), else_=0)
            ).label("sentiment_negative"),
            func.sum(
                case(
                    (or_(rc.llm_sentiment == "neutral", rc.llm_sentiment.is_(None)), 1),
                    else_=0,
                )
            ).label("sentiment_neutral"),
            func.sum(
                case((rc.llm_category == "講義内容", 1), else_=0)
            ).label("category_lecture_content"),
            func.sum(
                case((rc.llm_category == "講義資料", 1), else_=0)
            ).label("category_lecture_material"),
            func.sum(
                case((rc.llm_category == "運営", 1), else_=0)
            ).label("category_operations"),
            func.sum(
                case(
                    (or_(rc.llm_importance_level == "low", rc.llm_importance_level.is_(None)), 1),
                    else_=0,
                )
            ).label("importance_low"),
            func.sum(
                case((rc.llm_importance_level == "medium", 1), else_=0)
            ).label("importance_medium"),
            func.sum(
                case((rc.llm_importance_level == "high", 1), else_=0)
            ).label("importance_high"),
        )
        .filter(*filters)
        .one()
    )

    summary.sentiment_positive = int(aggregates.sentiment_positive or 0)
    summary.sentiment_negative = int(aggregates.sentiment_negative or 0)
    summary.sentiment_neutral = int(aggregates.sentiment_neutral or 0)

    summary.category_lecture_content = int(aggregates.category_lecture_content or 0)
    summary.category_lecture_material = int(aggregates.category_lecture_material or 0)
    summary.category_operations = int(aggregates.category_operations or 0)
    total_comments = int(aggregates.total_comments or 0)
    summary.category_other = max(
        total_comments
        - summary.category_lecture_content
        - summary.category_lecture_material
        - summary.category_operations,
        0,
    )

    summary.importance_low = int(aggregates.importance_low or 0)
    summary.importance_medium = int(aggregates.importance_medium or 0)
    summary.importance_high = int(aggregates.importance_high or 0)
    summary.important_comments_count = summary.importance_medium + summary.importance_high
    summary.comments_count = total_comments


def _nps_breakdown_from_scores(
    scores: list[int | float],
    *,
    nps_scale: int = 10,
) -> dict:
    promoters = passives = detractors = 0
    for value in (v for v in scores if v is not None):
        score = int(value)
        if nps_scale == 10:
            if 9 <= score <= 10:
                promoters += 1
            elif 7 <= score <= 8:
                passives += 1
            elif 0 <= score <= 6:
                detractors += 1
        else:
            if score == 5:
                promoters += 1
            elif score in (3, 4):
                passives += 1
            elif score in (1, 2):
                detractors += 1

    total = len([v for v in scores if v is not None])
    return _nps_breakdown_from_counts(promoters, passives, detractors, total)


def _nps_breakdown_from_db(
    db: Session, survey_batch_id: int, *, nps_scale: int
) -> dict:
    score_column = models.SurveyResponse.score_recommend_to_friend
    if nps_scale == 10:
        promoters_case = case((score_column.between(9, 10), 1), else_=0)
        passives_case = case((score_column.between(7, 8), 1), else_=0)
        detractors_case = case((score_column.between(0, 6), 1), else_=0)
    else:
        promoters_case = case((score_column == 5, 1), else_=0)
        passives_case = case((score_column.in_((3, 4)), 1), else_=0)
        detractors_case = case((score_column.in_((1, 2)), 1), else_=0)

    promoters, passives, detractors, total = (
        int(value or 0)
        for value in db.query(
            func.sum(promoters_case),
            func.sum(passives_case),
            func.sum(detractors_case),
            func.count(score_column),
        )
        .filter(models.SurveyResponse.survey_batch_id == survey_batch_id)
        .one()
    )

    return _nps_breakdown_from_counts(promoters, passives, detractors, total)


def _nps_breakdown_from_counts(
    promoters: int, passives: int, detractors: int, total: int
) -> dict:
    if not total:
        return {
            "score": 0.0,
            "promoters": 0,
            "passives": 0,
            "detractors": 0,
            "total": 0,
        }
    nps = round((promoters - detractors) * 100.0 / total, 1)
    return {
        "score": nps,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total": total,
    }


def _maybe_round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)
