from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.db import models
from app.db.session import get_db

router = APIRouter()

_SCORE_FIELD_MAP = {
    "overall_satisfaction": "avg_satisfaction_overall",
    "content_volume": "avg_content_volume",
    "content_understanding": "avg_content_understanding",
    "content_announcement": "avg_content_announcement",
    "instructor_overall": "avg_instructor_overall",
    "instructor_time": "avg_instructor_time",
    "instructor_qa": "avg_instructor_qa",
    "instructor_speaking": "avg_instructor_speaking",
    "self_preparation": "avg_self_preparation",
    "self_motivation": "avg_self_motivation",
    "self_future": "avg_self_future",
}


def _choose_effective_batches(
    rows: Iterable[models.SurveyBatch],
) -> Dict[int, models.SurveyBatch]:
    """講義IDごとの代表バッチを選択する。

    優先順位:
    1. uploaded_at の新しいもの (finalized_at はモデルにないため)
    """
    by_lecture_id: Dict[int, List[models.SurveyBatch]] = defaultdict(list)
    for row in rows:
        by_lecture_id[row.lecture_id].append(row)

    chosen: Dict[int, models.SurveyBatch] = {}
    for lecture_id, batches in by_lecture_id.items():
        # batch_type='confirmed' を優先すべきだが、
        # ここでは単純に uploaded_at が最新のものを採用する（または呼び出し元でフィルタリング済みと仮定）
        # confirmed があればそれを優先するロジックを追加
        confirmed = [b for b in batches if b.batch_type == "confirmed"]
        if confirmed:
            chosen[lecture_id] = max(confirmed, key=lambda b: b.uploaded_at)
        else:
            chosen[lecture_id] = max(batches, key=lambda b: b.uploaded_at)
    return chosen


def _pick_summary(
    batch_id: int,
    version: str,
    summaries: Dict[int, models.SurveySummary],
) -> Optional[models.SurveySummary]:
    # version は旧設計互換のため残しているが、現在はバッチ単位で単一サマリのみを保持する。
    return summaries.get(batch_id)


def _pick_comment_summary(
    batch_id: int,
    version: str,
    summaries: Dict[int, List[models.CommentSummary]],
) -> List[models.CommentSummary]:
    # version は旧設計互換のため残しているが、現在はバッチ単位で単一集合のみを保持する。
    return summaries.get(batch_id) or []


def _aggregate_scores(
    summaries: List[models.SurveySummary],
) -> Dict[str, Optional[float]]:
    totals: Dict[str, float] = {k: 0.0 for k in _SCORE_FIELD_MAP.keys()}
    weights: Dict[str, int] = {k: 0 for k in _SCORE_FIELD_MAP.keys()}
    for s in summaries:
        weight = s.response_count or 0
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
    promoters = sum(int(s.promoter_count or 0) for s in summaries)
    passives = sum(int(s.passive_count or 0) for s in summaries)
    detractors = sum(int(s.detractor_count or 0) for s in summaries)
    total = sum(int(s.response_count or 0) for s in summaries)
    score = round((promoters - detractors) * 100.0 / total, 1) if total else 0.0
    return {
        "score": score,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total": total,
    }


def _comment_stats(
    rows: List[models.CommentSummary],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], Dict[str, int], int, int]:
    sentiments = {"positive": 0, "negative": 0, "neutral": 0}
    categories = {
        "lecture_content": 0,
        "lecture_material": 0,
        "operations": 0,
        "other": 0,
    }
    priority = {"low": 0, "medium": 0, "high": 0}

    fix_difficulty = {"easy": 0, "hard": 0}

    for row in rows:
        if row.analysis_type == "sentiment" and row.label in sentiments:
            sentiments[row.label] += int(row.count or 0)
        elif row.analysis_type == "category":
            key_map = {
                "content": "lecture_content",
                "materials": "lecture_material",
                "operations": "operations",
                "other": "other",
            }
            mapped = key_map.get(row.label)
            if mapped and mapped in categories:
                categories[mapped] += int(row.count or 0)
        elif row.analysis_type == "priority" and row.label in priority:
            priority[row.label] += int(row.count or 0)
        elif row.analysis_type == "fix_difficulty" and row.label in fix_difficulty:
            fix_difficulty[row.label] += int(row.count or 0)

    comments_count = max(
        sum(sentiments.values()),
        sum(categories.values()),
        sum(priority.values()),
        sum(fix_difficulty.values()),
    )
    # important_count is now priority_high + priority_medium
    important_count = priority["medium"] + priority["high"]
    return (
        sentiments,
        categories,
        priority,
        fix_difficulty,
        comments_count,
        important_count,
    )


def _aggregate_sentiments(
    summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    sentiments, _, _, _, _, _ = _comment_stats(summaries)
    return sentiments


def _aggregate_categories(
    summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    _, categories, _, _, _, _ = _comment_stats(summaries)
    return categories


def _aggregate_fix_difficulty(
    summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    _, _, _, fix_difficulty, _, _ = _comment_stats(summaries)
    return fix_difficulty


def _aggregate_counts(
    survey_summaries: List[models.SurveySummary],
    comment_summaries: List[models.CommentSummary],
) -> Dict[str, int]:
    _, _, _, _, comments_count, important_from_comments = _comment_stats(
        comment_summaries
    )
    return {
        "responses": sum(int(s.response_count or 0) for s in survey_summaries),
        "comments": comments_count,
        "important_comments": important_from_comments,
    }


def _load_summaries(
    db: Session,
    batch_ids: List[int],
) -> Tuple[
    Dict[int, models.SurveySummary],
    Dict[int, List[models.CommentSummary]],
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
    # analysis_version カラム廃止に伴い、バッチID単位で集約する。
    survey_map: Dict[int, models.SurveySummary] = {
        row.survey_batch_id: row for row in survey_rows
    }
    comment_map: Dict[int, List[models.CommentSummary]] = {}
    for row in comment_rows:
        comment_map.setdefault(row.survey_batch_id, []).append(row)
    return survey_map, comment_map


def _format_scores(
    summary: Optional[models.SurveySummary],
) -> Dict[str, Optional[float]]:
    if not summary:
        return {k: None for k in _SCORE_FIELD_MAP.keys()}
    result = {}
    for out_key, attr in _SCORE_FIELD_MAP.items():
        val = getattr(summary, attr)
        result[out_key] = float(val) if val is not None else None
    return result


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

    # 同一コースの全講義を取得
    lectures = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.name == lecture.name,
            models.Lecture.academic_year == lecture.academic_year,
            models.Lecture.term == lecture.term,
        )
        .all()
    )
    lecture_ids = [l.id for l in lectures]

    batches = (
        db.query(models.SurveyBatch)
        .options(joinedload(models.SurveyBatch.lecture))
        .filter(models.SurveyBatch.lecture_id.in_(lecture_ids))
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
    flat_comment_rows = [row for rows in comment_summaries for row in rows]

    scores = _aggregate_scores(survey_summaries)
    nps = _aggregate_nps(survey_summaries)
    counts = _aggregate_counts(survey_summaries, flat_comment_rows)
    sentiments = _aggregate_sentiments(flat_comment_rows)
    categories = _aggregate_categories(flat_comment_rows)
    # Add priority aggregation here if needed for overview, usually overview returns it inside 'counts' or similar?
    # But dashboard_overview return dict has no 'priority' key in original code?
    # Wait, the user manual edit Step 810 shows dashboard_per_lecture returning it.
    # dashboard_overview usually aggregates counts.
    # I will add priority to dashboard_overview return to be safe/complete.
    _, _, priority, fix_difficulty, _, _ = _comment_stats(flat_comment_rows)

    timeline = []
    timeline = []
    # lecture_on 順にソートするためにバッチから講義情報を参照
    sorted_batches = sorted(
        chosen_batches, key=lambda b: b.lecture.lecture_on if b.lecture else date.min
    )

    for batch in sorted_batches:
        summary = _pick_summary(batch.id, version or "final", survey_map)
        timeline.append(
            {
                "lecture_number": batch.lecture.session if batch.lecture else "",
                "batch_id": batch.id,
                "nps": (
                    float(summary.nps) if summary and summary.nps is not None else 0.0
                ),
                "response_count": summary.response_count if summary else 0,
                "avg_overall_satisfaction": (
                    float(summary.avg_satisfaction_overall)
                    if summary and summary.avg_satisfaction_overall is not None
                    else None
                ),
            }
        )

    return {
        "scores": scores,
        "nps": nps,
        "counts": counts,
        "sentiments": sentiments,
        "categories": categories,
        "priority": priority,
        "fix_difficulty": fix_difficulty,
        "timeline": timeline,
    }


@router.get("/dashboard/{lecture_id}/per_lecture")
def dashboard_per_lecture(
    lecture_id: int,
    version: Optional[str] = Query(default="final", enum=["final", "preliminary"]),
    db: Session = Depends(get_db),
) -> dict:
    """講義番号ごとの詳細（スコア・NPS・感情/カテゴリ内訳）を返す。"""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="講義が見つかりません")

    # 同一コースの全講義を取得
    lectures = (
        db.query(models.Lecture)
        .filter(
            models.Lecture.name == lecture.name,
            models.Lecture.academic_year == lecture.academic_year,
            models.Lecture.term == lecture.term,
        )
        .all()
    )
    lecture_ids = [l.id for l in lectures]

    batches = (
        db.query(models.SurveyBatch)
        .options(joinedload(models.SurveyBatch.lecture))
        .filter(models.SurveyBatch.lecture_id.in_(lecture_ids))
        .all()
    )
    if not batches:
        return {"lectures": []}

    chosen = _choose_effective_batches(batches)
    chosen_sorted = sorted(chosen.items(), key=lambda x: x[0])
    batch_ids = [b.id for _, b in chosen_sorted]
    survey_map, comment_map = _load_summaries(db, batch_ids)

    lectures_payload: List[dict] = []
    # lecture_on 順にソート
    sorted_batches = sorted(
        list(chosen.values()),
        key=lambda b: b.lecture.lecture_on if b.lecture else date.min,
    )

    for batch in sorted_batches:
        summary = _pick_summary(batch.id, version or "final", survey_map)
        comment_summary = _pick_comment_summary(
            batch.id, version or "final", comment_map
        )
        lectures_payload.append(
            {
                "lecture_number": batch.lecture.session if batch.lecture else "",
                "batch_id": batch.id,
                "scores": _format_scores(summary),
                "nps": {
                    "score": (
                        float(summary.nps)
                        if summary and summary.nps is not None
                        else 0.0
                    ),
                    "promoters": summary.promoter_count if summary else 0,
                    "passives": summary.passive_count if summary else 0,
                    "detractors": summary.detractor_count if summary else 0,
                    "total": summary.response_count if summary else 0,
                },
                "sentiments": _aggregate_sentiments(comment_summary),
                "categories": _aggregate_categories(comment_summary),
                "priority": {
                    "low": _comment_stats(comment_summary)[2]["low"],
                    "medium": _comment_stats(comment_summary)[2]["medium"],
                    "high": _comment_stats(comment_summary)[2]["high"],
                    "priority_comments": _comment_stats(comment_summary)[5],
                },
                "fix_difficulty": _comment_stats(comment_summary)[3],
                "counts": {
                    "responses": summary.response_count if summary else 0,
                    "comments": _comment_stats(comment_summary)[4],
                    "important_comments": _comment_stats(comment_summary)[5],
                },
            }
        )

    return {"lectures": lectures_payload}
