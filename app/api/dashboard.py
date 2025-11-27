from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db

router = APIRouter()

_SCORE_FIELD_MAP = {
    "overall_satisfaction": "score_overall_satisfaction",
    "content_volume": "score_content_volume",
    "content_understanding": "score_content_understanding",
    "content_announcement": "score_content_announcement",
    "instructor_overall": "score_instructor_overall",
    "instructor_time": "score_instructor_time",
    "instructor_qa": "score_instructor_qa",
    "instructor_speaking": "score_instructor_speaking",
    "self_preparation": "score_self_preparation",
    "self_motivation": "score_self_motivation",
    "self_future": "score_self_future",
}


def _choose_effective_batches(
    rows: Iterable[models.SurveyBatch],
) -> Dict[int, models.SurveyBatch]:
    """講義番号ごとの代表バッチを選択する。

    優先順位:
    1. finalized_at の新しいもの
    2. upload_timestamp の新しいもの
    """
    by_number: Dict[int, List[models.SurveyBatch]] = defaultdict(list)
    for row in rows:
        by_number[row.lecture_number].append(row)

    chosen: Dict[int, models.SurveyBatch] = {}
    for lecture_number, batches in by_number.items():
        finalized = [b for b in batches if b.finalized_at is not None]
        if finalized:
            chosen[lecture_number] = max(finalized, key=lambda b: b.finalized_at)
        else:
            chosen[lecture_number] = max(batches, key=lambda b: b.upload_timestamp)
    return chosen


def _pick_summary(
    batch_id: int,
    version: str,
    summaries: Dict[Tuple[int, str], models.SurveySummary],
) -> Optional[models.SurveySummary]:
    return summaries.get((batch_id, version)) or summaries.get(
        (batch_id, "preliminary")
    )


def _pick_comment_summary(
    batch_id: int,
    version: str,
    summaries: Dict[Tuple[int, str], models.CommentSummary],
) -> Optional[models.CommentSummary]:
    return summaries.get((batch_id, version)) or summaries.get(
        (batch_id, "preliminary")
    )


def _aggregate_scores(
    summaries: List[models.SurveySummary],
) -> Dict[str, Optional[float]]:
    totals: Dict[str, float] = {k: 0.0 for k in _SCORE_FIELD_MAP.keys()}
    weights: Dict[str, int] = {k: 0 for k in _SCORE_FIELD_MAP.keys()}
    for s in summaries:
        weight = s.responses_count or 0
        if weight <= 0:
            continue
        for out_key, attr in _SCORE_FIELD_MAP.items():
            value = getattr(s, attr)
            if value is not None:
                totals[out_key] += float(value) * weight
                weights[out_key] += weight
    result: Dict[str, Optional[float]] = {}
    for key in _SCORE_FIELD_MAP.keys():
        if weights[key] > 0:
            result[key] = round(totals[key] / weights[key], 2)
        else:
            result[key] = None
    return result


def _aggregate_nps(
    summaries: List[models.SurveySummary],
) -> Dict[str, float | int]:
    promoters = sum(int(s.nps_promoters or 0) for s in summaries)
    passives = sum(int(s.nps_passives or 0) for s in summaries)
    detractors = sum(int(s.nps_detractors or 0) for s in summaries)
    total = sum(int(s.nps_total or 0) for s in summaries)
    score = round((promoters - detractors) * 100.0 / total, 1) if total else 0.0
    return {
        "score": score,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total": total,
    }


def _aggregate_sentiments(
    summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    return {
        "positive": sum(int(s.sentiment_positive or 0) for s in summaries),
        "negative": sum(int(s.sentiment_negative or 0) for s in summaries),
        "neutral": sum(int(s.sentiment_neutral or 0) for s in summaries),
    }


def _aggregate_categories(
    summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    return {
        "lecture_content": sum(int(s.category_lecture_content or 0) for s in summaries),
        "lecture_material": sum(
            int(s.category_lecture_material or 0) for s in summaries
        ),
        "operations": sum(int(s.category_operations or 0) for s in summaries),
        "other": sum(int(s.category_other or 0) for s in summaries),
    }


def _aggregate_counts(
    survey_summaries: List[models.SurveySummary],
    comment_summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    return {
        "responses": sum(int(s.responses_count or 0) for s in survey_summaries),
        "comments": sum(int(s.comments_count or 0) for s in survey_summaries),
        "important_comments": sum(
            int(c.important_comments_count or 0) for c in comment_summaries
        ),
    }


def _load_summaries(
    db: Session,
    batch_ids: List[int],
) -> Tuple[
    Dict[Tuple[int, str], models.SurveySummary],
    Dict[Tuple[int, str], models.CommentSummary],
]:
    survey_rows = (
        db.query(models.SurveySummary)
        .filter(models.SurveySummary.survey_batch_id.in_(batch_ids))
        .all()
    )
    comment_rows = (
        db.query(models.CommentSummary)
        .filter(models.CommentSummary.survey_batch_id.in_(batch_ids))
        .all()
    )
    survey_map = {
        (row.survey_batch_id, row.analysis_version): row for row in survey_rows
    }
    comment_map = {
        (row.survey_batch_id, row.analysis_version): row for row in comment_rows
    }
    return survey_map, comment_map


def _format_scores(
    summary: Optional[models.SurveySummary],
) -> Dict[str, Optional[float]]:
    if not summary:
        return {k: None for k in _SCORE_FIELD_MAP.keys()}
    return {
        out_key: getattr(summary, attr) for out_key, attr in _SCORE_FIELD_MAP.items()
    }


@router.get("/dashboard/{lecture_id}/overview")
def dashboard_overview(
    lecture_id: int,
    version: Optional[str] = Query(default="final", enum=["final", "preliminary"]),
    db: Session = Depends(get_db),
) -> dict:
    """講義のダッシュボード全体の集計値を返す（事前計算テーブルを使用）。"""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="講義が見つかりません")

    batches = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.lecture_id == lecture_id)
        .all()
    )
    if not batches:
        return {
            "scores": {},
            "nps": {
                "score": 0.0,
                "promoters": 0,
                "passives": 0,
                "detractors": 0,
                "total": 0,
            },
            "counts": {"responses": 0, "comments": 0, "important_comments": 0},
            "sentiments": {"positive": 0, "negative": 0, "neutral": 0},
            "categories": {
                "lecture_content": 0,
                "lecture_material": 0,
                "operations": 0,
                "other": 0,
            },
            "timeline": [],
        }

    chosen = _choose_effective_batches(batches)
    chosen_batches = list(chosen.values())
    batch_ids = [b.id for b in chosen_batches]

    survey_map, comment_map = _load_summaries(db, batch_ids)

    survey_summaries = [
        _pick_summary(b.id, version or "final", survey_map) for b in chosen_batches
    ]
    comment_summaries = [
        _pick_comment_summary(b.id, version or "final", comment_map)
        for b in chosen_batches
    ]
    survey_summaries = [s for s in survey_summaries if s]
    comment_summaries = [c for c in comment_summaries if c]

    scores = _aggregate_scores(survey_summaries)
    nps = _aggregate_nps(survey_summaries)
    counts = _aggregate_counts(survey_summaries, comment_summaries)
    sentiments = _aggregate_sentiments(comment_summaries)
    categories = _aggregate_categories(comment_summaries)

    timeline = []
    for lecture_num, batch in sorted(chosen.items(), key=lambda x: x[0]):
        summary = _pick_summary(batch.id, version or "final", survey_map)
        timeline.append(
            {
                "lecture_number": lecture_num,
                "batch_id": batch.id,
                "nps": summary.nps_score if summary else 0.0,
                "response_count": summary.responses_count if summary else 0,
                "avg_overall_satisfaction": (
                    summary.score_overall_satisfaction if summary else None
                ),
            }
        )

    return {
        "scores": scores,
        "nps": nps,
        "counts": counts,
        "sentiments": sentiments,
        "categories": categories,
        "timeline": timeline,
    }


@router.get("/dashboard/{lecture_id}/per_lecture")
def dashboard_per_lecture(
    lecture_id: int,
    version: Optional[str] = Query(default="final", enum=["final", "preliminary"]),
    db: Session = Depends(get_db),
) -> dict:
    """講義番号ごとの詳細（スコア・NPS・感情/カテゴリ内訳）を返す。"""
    batches = (
        db.query(models.SurveyBatch)
        .filter(models.SurveyBatch.lecture_id == lecture_id)
        .all()
    )
    if not batches:
        return {"lectures": []}

    chosen = _choose_effective_batches(batches)
    chosen_sorted = sorted(chosen.items(), key=lambda x: x[0])
    batch_ids = [b.id for _, b in chosen_sorted]
    survey_map, comment_map = _load_summaries(db, batch_ids)

    lectures_payload: List[dict] = []
    for lecture_num, batch in chosen_sorted:
        summary = _pick_summary(batch.id, version or "final", survey_map)
        comment_summary = _pick_comment_summary(
            batch.id, version or "final", comment_map
        )
        lectures_payload.append(
            {
                "lecture_number": lecture_num,
                "batch_id": batch.id,
                "scores": _format_scores(summary),
                "nps": {
                    "score": summary.nps_score if summary else 0.0,
                    "promoters": summary.nps_promoters if summary else 0,
                    "passives": summary.nps_passives if summary else 0,
                    "detractors": summary.nps_detractors if summary else 0,
                    "total": summary.nps_total if summary else 0,
                },
                "sentiments": _aggregate_sentiments(
                    [comment_summary] if comment_summary else []
                ),
                "categories": _aggregate_categories(
                    [comment_summary] if comment_summary else []
                ),
                "importance": {
                    "low": comment_summary.importance_low if comment_summary else 0,
                    "medium": (
                        comment_summary.importance_medium if comment_summary else 0
                    ),
                    "high": comment_summary.importance_high if comment_summary else 0,
                    "important_comments": (
                        comment_summary.important_comments_count
                        if comment_summary
                        else 0
                    ),
                },
                "counts": {
                    "responses": summary.responses_count if summary else 0,
                    "comments": summary.comments_count if summary else 0,
                    "important_comments": (
                        comment_summary.important_comments_count
                        if comment_summary
                        else 0
                    ),
                },
            }
        )

    return {"lectures": lectures_payload}
