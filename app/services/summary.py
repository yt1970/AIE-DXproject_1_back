from __future__ import annotations

from datetime import UTC, datetime
from typing import Dict, Optional, Tuple

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
    student_attribute: str | None = None,
    nps_scale: int = 10,
) -> Tuple[models.SurveySummary, Dict[str, int]]:
    """
    サーベイバッチの集計を計算し、SurveySummary/CommentSummaryをアップサートする。
    """
    db.flush()

    survey_summary = (
        db.query(models.SurveySummary)
        .filter(
            models.SurveySummary.survey_batch_id == survey_batch.id,
            models.SurveySummary.analysis_version == version,
            models.SurveySummary.student_attribute == (student_attribute or "ALL"),
        )
        .first()
    )
    if not survey_summary:
        survey_summary = models.SurveySummary(
            survey_batch_id=survey_batch.id,
            analysis_version=version,
            student_attribute=student_attribute or "ALL",
        )

    _populate_survey_summary(
        db,
        survey_summary,
        survey_batch.id,
        nps_scale,
        student_attribute=student_attribute,
    )
    comment_counts = _refresh_comment_summary(
        db, survey_batch.id, version, student_attribute=student_attribute
    )
    _populate_score_distributions(
        db, survey_batch.id, student_attribute=student_attribute
    )
    # サマリー間でカウントを揃える
    survey_summary.comments_count = comment_counts.get("comments_count", 0)
    survey_summary.important_comments_count = comment_counts.get(
        "important_comments_count", 0
    )

    now = datetime.now(UTC)
    survey_summary.updated_at = now
    if not survey_summary.created_at:
        survey_summary.created_at = now

    db.add(survey_summary)
    return survey_summary, comment_counts


def _populate_survey_summary(
    db: Session,
    summary: models.SurveySummary,
    survey_batch_id: int,
    nps_scale: int,
    student_attribute: str | None = None,
) -> None:
    score_fields = {
        "score_overall_satisfaction": models.SurveyResponse.score_satisfaction_overall,
        "score_content_volume": models.SurveyResponse.score_content_volume,
        "score_content_understanding": models.SurveyResponse.score_content_understanding,
        "score_content_announcement": models.SurveyResponse.score_content_announcement,
        "score_instructor_overall": models.SurveyResponse.score_instructor_overall,
        "score_instructor_time": models.SurveyResponse.score_instructor_time,
        "score_instructor_qa": models.SurveyResponse.score_instructor_qa,
        "score_instructor_speaking": models.SurveyResponse.score_instructor_speaking,
        "score_self_preparation": models.SurveyResponse.score_self_preparation,
        "score_self_motivation": models.SurveyResponse.score_self_motivation,
        "score_self_future": models.SurveyResponse.score_self_future,
    }

    aggregates = (
        db.query(
            *[func.avg(col) for col in score_fields.values()],
            func.count(models.SurveyResponse.id),
        )
        .filter(models.SurveyResponse.survey_batch_id == survey_batch_id)
        .filter(
            models.SurveyResponse.student_attribute == student_attribute
            if student_attribute
            else True
        )
        .one()
    )

    for (field_name, _), value in zip(score_fields.items(), aggregates):
        setattr(summary, field_name, _maybe_round(value))

    responses_count = aggregates[-1]
    summary.response_count = int(responses_count) if responses_count is not None else 0

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


def _refresh_comment_summary(
    db: Session,
    survey_batch_id: int,
    version: str,
    student_attribute: str | None = None,
) -> Dict[str, int]:
    attr = student_attribute or "ALL"
    db.query(models.CommentSummary).filter(
        models.CommentSummary.survey_batch_id == survey_batch_id,
        models.CommentSummary.analysis_version == version,
        models.CommentSummary.student_attribute == attr,
    ).delete(synchronize_session=False)

    filters = [models.ResponseComment.survey_batch_id == survey_batch_id]
    vf = _version_filter(version)
    if vf is not None:
        filters.append(vf)
    query = db.query(models.ResponseComment)
    if student_attribute:
        query = query.join(models.ResponseComment.survey_response)
        filters.append(models.SurveyResponse.student_attribute == student_attribute)

    rc = models.ResponseComment
    aggregates = (
        query.with_entities(
            func.count(1).label("total_comments"),
            func.sum(
                case(
                    (
                        or_(rc.llm_sentiment_type == "positive", rc.llm_sentiment_type == "ポジティブ"),
                        1,
                    ),
                    else_=0,
                )
            ).label("sentiment_positive"),
            func.sum(
                case(
                    (
                        or_(rc.llm_sentiment_type == "negative", rc.llm_sentiment_type == "ネガティブ"),
                        1,
                    ),
                    else_=0,
                )
            ).label("sentiment_negative"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_sentiment_type == "neutral",
                            rc.llm_sentiment_type == "ニュートラル",
                            rc.llm_sentiment_type.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sentiment_neutral"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_category == "content",
                            rc.llm_category == "講義内容",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("category_content"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_category == "materials",
                            rc.llm_category == "講義資料",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("category_materials"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_category == "operations",
                            rc.llm_category == "運営",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("category_operations"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_importance_level == "low",
                            rc.llm_importance_level == "低",
                            rc.llm_importance_level.is_(None),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("importance_low"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_importance_level == "medium",
                            rc.llm_importance_level == "中",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("importance_medium"),
            func.sum(
                case(
                    (
                        or_(
                            rc.llm_importance_level == "high",
                            rc.llm_importance_level == "高",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("importance_high"),
        )
        .filter(*filters)
        .one()
    )

    total_comments = int(aggregates.total_comments or 0)
    sentiment_counts = {
        "positive": int(aggregates.sentiment_positive or 0),
        "negative": int(aggregates.sentiment_negative or 0),
        "neutral": int(aggregates.sentiment_neutral or 0),
    }
    category_counts = {
        "content": int(aggregates.category_content or 0),
        "materials": int(aggregates.category_materials or 0),
        "operations": int(aggregates.category_operations or 0),
    }
    category_counts["other"] = max(
        total_comments
        - category_counts["content"]
        - category_counts["materials"]
        - category_counts["operations"],
        0,
    )
    importance_counts = {
        "low": int(aggregates.importance_low or 0),
        "medium": int(aggregates.importance_medium or 0),
        "high": int(aggregates.importance_high or 0),
    }

    now = datetime.now(UTC)
    rows = []
    for label, value in sentiment_counts.items():
        rows.append(
            models.CommentSummary(
                survey_batch_id=survey_batch_id,
                analysis_version=version,
                student_attribute=attr,
                analysis_type="sentiment",
                label=label,
                count=value,
                created_at=now,
            )
        )
    for label, value in category_counts.items():
        rows.append(
            models.CommentSummary(
                survey_batch_id=survey_batch_id,
                analysis_version=version,
                student_attribute=attr,
                analysis_type="category",
                label=label,
                count=value,
                created_at=now,
            )
        )
    for label, value in importance_counts.items():
        rows.append(
            models.CommentSummary(
                survey_batch_id=survey_batch_id,
                analysis_version=version,
                student_attribute=attr,
                analysis_type="importance",
                label=label,
                count=value,
                created_at=now,
            )
        )

    db.add_all(rows)
    return {
        "comments_count": total_comments,
        "important_comments_count": importance_counts["medium"]
        + importance_counts["high"],
    }


def _populate_score_distributions(
    db: Session, survey_batch_id: int, student_attribute: str | None = None
) -> None:
    """スコア分布をscore_distributionに保存する。既存データは同条件で削除。"""
    if not hasattr(models, "ScoreDistribution"):
        return
    score_columns = [
        "score_satisfaction_overall",
        "score_content_volume",
        "score_content_understanding",
        "score_content_announcement",
        "score_instructor_overall",
        "score_instructor_time",
        "score_instructor_qa",
        "score_instructor_speaking",
        "score_self_preparation",
        "score_self_motivation",
        "score_self_future",
        "score_recommend_friend",
    ]

    # 既存分布を削除
    db.query(models.ScoreDistribution).filter(
        models.ScoreDistribution.survey_batch_id == survey_batch_id,
        models.ScoreDistribution.student_attribute == (student_attribute or "ALL"),
    ).delete(synchronize_session=False)

    base_query = db.query(models.SurveyResponse).filter(
        models.SurveyResponse.survey_batch_id == survey_batch_id
    )
    if student_attribute:
        base_query = base_query.filter(
            models.SurveyResponse.student_attribute == student_attribute
        )

    for col_name in score_columns:
        col = getattr(models.SurveyResponse, col_name, None)
        if col is None:
            continue
        rows = (
            db.query(col.label("score_value"), func.count(1).label("count"))
            .filter(col.isnot(None))
            .filter(models.SurveyResponse.survey_batch_id == survey_batch_id)
            .filter(
                models.SurveyResponse.student_attribute == student_attribute
                if student_attribute
                else True
            )
            .group_by(col)
            .all()
        )
        for row in rows:
            db.add(
                models.ScoreDistribution(
                    survey_batch_id=survey_batch_id,
                    student_attribute=student_attribute or "ALL",
                    question_key=col_name,
                    score_value=int(row.score_value),
                    count=int(row.count),
                )
            )
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
    score_column = models.SurveyResponse.score_recommend_friend
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
