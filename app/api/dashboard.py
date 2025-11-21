from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db

router = APIRouter()


def _choose_effective_files(
    rows: Iterable[models.UploadedFile],
) -> Dict[int, models.UploadedFile]:
    """Choose the representative file per lecture_number.

    Preference:
    1) finalized (latest finalized_at)
    2) otherwise latest upload_timestamp
    """
    by_number: Dict[int, List[models.UploadedFile]] = defaultdict(list)
    for row in rows:
        by_number[row.lecture_number].append(row)

    chosen: Dict[int, models.UploadedFile] = {}
    for lecture_number, files in by_number.items():
        finalized = [f for f in files if f.finalized_at is not None]
        if finalized:
            chosen[lecture_number] = max(finalized, key=lambda f: f.finalized_at)
        else:
            chosen[lecture_number] = max(files, key=lambda f: f.upload_timestamp)
    return chosen


def _version_filter(version: str | None):
    """Return filter expression for Comment.analysis_version."""
    if version == "final":
        return models.Comment.analysis_version == "final"
    if version == "preliminary":
        return or_(
            models.Comment.analysis_version == "preliminary",
            models.Comment.analysis_version.is_(None),
        )
    return None


def _compute_average_scores(db: Session, file_ids: List[int]) -> Dict[str, Optional[float]]:
    """Compute averages for survey scores (excluding recommend_to_friend)."""
    if not file_ids:
        return {}
    s = (
        db.query(
            func.avg(models.SurveyResponse.score_satisfaction_overall),
            func.avg(models.SurveyResponse.score_satisfaction_content_volume),
            func.avg(models.SurveyResponse.score_satisfaction_content_understanding),
            func.avg(models.SurveyResponse.score_satisfaction_content_announcement),
            func.avg(models.SurveyResponse.score_satisfaction_instructor_overall),
            func.avg(models.SurveyResponse.score_satisfaction_instructor_efficiency),
            func.avg(models.SurveyResponse.score_satisfaction_instructor_response),
            func.avg(models.SurveyResponse.score_satisfaction_instructor_clarity),
            func.avg(models.SurveyResponse.score_self_preparation),
            func.avg(models.SurveyResponse.score_self_motivation),
            func.avg(models.SurveyResponse.score_self_applicability),
        )
        .filter(models.SurveyResponse.file_id.in_(file_ids))
        .one()
    )
    return {
        "overall_satisfaction": _maybe_round(s[0]),
        "content_volume": _maybe_round(s[1]),
        "content_understanding": _maybe_round(s[2]),
        "content_announcement": _maybe_round(s[3]),
        "instructor_overall": _maybe_round(s[4]),
        "instructor_efficiency": _maybe_round(s[5]),
        "instructor_response": _maybe_round(s[6]),
        "instructor_clarity": _maybe_round(s[7]),
        "self_preparation": _maybe_round(s[8]),
        "self_motivation": _maybe_round(s[9]),
        "self_applicability": _maybe_round(s[10]),
    }


def _maybe_round(value: Optional[float]) -> Optional[float]:
    """Round numeric values for stable UI display."""
    if value is None:
        return None
    return round(float(value), 2)


def _compute_nps(
    db: Session, file_ids: List[int], *, nps_scale: int = 10
) -> Dict[str, float | int]:
    """Compute NPS and breakdown for 5 or 10 point scales.

    - nps_scale=5: detractors={1,2}, passives={3,4}, promoters={5}
    - nps_scale=10: detractors=0..6, passives=7..8, promoters=9..10
    """
    if not file_ids:
        return {
            "score": 0.0,
            "promoters_percent": 0.0,
            "passives_percent": 0.0,
            "detractors_percent": 0.0,
            "promoters": 0,
            "passives": 0,
            "detractors": 0,
            "total": 0,
        }
    rows = (
        db.query(models.SurveyResponse.score_recommend_to_friend)
        .filter(models.SurveyResponse.file_id.in_(file_ids))
        .all()
    )
    scores = [r[0] for r in rows if r[0] is not None]
    if not scores:
        return {
            "score": 0.0,
            "promoters_percent": 0.0,
            "passives_percent": 0.0,
            "detractors_percent": 0.0,
            "promoters": 0,
            "passives": 0,
            "detractors": 0,
            "total": 0,
        }
    total = len(scores)
    if nps_scale == 10:
        promoters = sum(1 for v in scores if v is not None and 9 <= int(v) <= 10)
        passives = sum(1 for v in scores if v is not None and 7 <= int(v) <= 8)
        detractors = sum(1 for v in scores if v is not None and 0 <= int(v) <= 6)
    else:
        promoters = sum(1 for v in scores if v == 5)
        passives = sum(1 for v in scores if v in (3, 4))
        detractors = sum(1 for v in scores if v in (1, 2))
    promoters_pct = round(promoters * 100.0 / total, 1)
    passives_pct = round(passives * 100.0 / total, 1)
    detractors_pct = round(detractors * 100.0 / total, 1)
    nps = round(promoters_pct - detractors_pct, 1)
    return {
        "score": nps,
        "promoters_percent": promoters_pct,
        "passives_percent": passives_pct,
        "detractors_percent": detractors_pct,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total": total,
    }


def _compute_nps_for_file(db: Session, file_id: int, *, nps_scale: int = 10) -> float:
    """Compute NPS score for a single file with the given scale."""
    data = _compute_nps(db, [file_id], nps_scale=nps_scale)
    return data["score"]


def _response_count(db: Session, file_id: int) -> int:
    """Count survey responses for a file."""
    return (
        db.query(models.SurveyResponse)
        .filter(models.SurveyResponse.file_id == file_id)
        .count()
    )


def _sentiment_breakdown(
    db: Session, file_ids: List[int], version: Optional[str]
) -> Dict[str, int]:
    """Aggregate counts for sentiment labels."""
    if not file_ids:
        return {"positive": 0, "negative": 0, "neutral": 0}
    q = db.query(models.Comment.llm_sentiment, func.count(1)).filter(
        models.Comment.file_id.in_(file_ids)
    )
    vf = _version_filter(version)
    if vf is not None:
        q = q.filter(vf)
    q = q.group_by(models.Comment.llm_sentiment)
    raw = dict((k or "neutral", int(v)) for k, v in q.all())
    return {
        "positive": raw.get("positive", 0),
        "negative": raw.get("negative", 0),
        "neutral": raw.get("neutral", 0),
    }


def _category_breakdown(
    db: Session, file_ids: List[int], version: Optional[str]
) -> List[Dict[str, int | str]]:
    """Aggregate counts for normalized categories."""
    if not file_ids:
        return []
    q = db.query(models.Comment.llm_category, func.count(1)).filter(
        models.Comment.file_id.in_(file_ids)
    )
    vf = _version_filter(version)
    if vf is not None:
        q = q.filter(vf)
    q = q.group_by(models.Comment.llm_category)
    rows = q.all()
    # Normalize null/unknown to "その他"
    result = []
    for category, count in rows:
        normalized = category or "その他"
        result.append({"category": normalized, "count": int(count)})
    # Ensure the four standard buckets are always included
    wanted = {"講義内容", "講義資料", "運営", "その他"}
    present = {r["category"] for r in result}
    for missing in sorted(wanted - present):
        result.append({"category": missing, "count": 0})
    # Stable order
    order = {"講義内容": 0, "講義資料": 1, "運営": 2, "その他": 3}
    result.sort(key=lambda r: order.get(r["category"], 99))
    return result


@router.get("/dashboard/{lecture_id}/overview")
def dashboard_overview(
    lecture_id: int,
    version: Optional[str] = Query(default="final", enum=["final", "preliminary"]),
    nps_scale: int = Query(default=10, ge=5, le=10),
    db: Session = Depends(get_db),
) -> dict:
    """Return overall dashboard aggregates for a lecture."""
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    files = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.lecture_id == lecture_id)
        .all()
    )
    if not files:
        return {
            "average_scores": {},
            "nps": {"score": 0.0, "promoters_percent": 0.0, "detractors_percent": 0.0},
            "nps_transition": [],
            "response_count_transition": [],
        }

    chosen = _choose_effective_files(files)
    chosen_ids = [f.file_id for f in chosen.values()]

    average_scores = _compute_average_scores(db, chosen_ids)
    nps = _compute_nps(db, chosen_ids, nps_scale=nps_scale)

    nps_transition = []
    response_count_transition = []
    for lecture_num, f in sorted(chosen.items(), key=lambda x: x[0]):
        nps_transition.append(
            {
                "lecture_num": lecture_num,
                "score": _compute_nps_for_file(db, f.file_id, nps_scale=nps_scale),
            }
        )
        response_count_transition.append(
            {"lecture_num": lecture_num, "count": _response_count(db, f.file_id)}
        )

    return {
        "average_scores": average_scores,
        "nps": nps,
        "nps_transition": nps_transition,
        "response_count_transition": response_count_transition,
    }


@router.get("/dashboard/{lecture_id}/per_lecture")
def dashboard_per_lecture(
    lecture_id: int,
    version: Optional[str] = Query(default="final", enum=["final", "preliminary"]),
    db: Session = Depends(get_db),
) -> dict:
    """Return per-lecture transitions and breakdowns for a lecture."""
    files = (
        db.query(models.UploadedFile)
        .filter(models.UploadedFile.lecture_id == lecture_id)
        .all()
    )
    if not files:
        return {
            "average_score_transitions": {},
            "sentiment_analysis": {"positive": 0, "negative": 0, "neutral": 0},
            "comment_categories": [],
            "self_evaluation_scores": {},
        }
    chosen = _choose_effective_files(files)
    chosen_sorted = sorted(chosen.items(), key=lambda x: x[0])
    chosen_ids = [f.file_id for _, f in chosen_sorted]

    # Average score transitions by lecture_num
    def avg_for_single(file_id: int) -> Dict[str, Optional[float]]:
        return _compute_average_scores(db, [file_id])

    transitions_by_metric: Dict[str, List[Optional[float]]] = defaultdict(list)
    for _, f in chosen_sorted:
        a = avg_for_single(f.file_id)
        for key in (
            "overall_satisfaction",
            "content_volume",
            "content_understanding",
            "instructor_overall",
        ):
            transitions_by_metric[key].append(a.get(key))

    sentiment = _sentiment_breakdown(db, chosen_ids, version)
    categories = _category_breakdown(db, chosen_ids, version)

    # Self-evaluation (overall average across chosen)
    self_scores = (
        db.query(
            func.avg(models.SurveyResponse.score_self_preparation),
            func.avg(models.SurveyResponse.score_self_motivation),
            func.avg(models.SurveyResponse.score_self_applicability),
        )
        .filter(models.SurveyResponse.file_id.in_(chosen_ids))
        .one()
    )
    self_evals = {
        "preparation": _maybe_round(self_scores[0]),
        "motivation": _maybe_round(self_scores[1]),
        "applicability": _maybe_round(self_scores[2]),
    }

    return {
        "average_score_transitions": transitions_by_metric,
        "sentiment_analysis": sentiment,
        "comment_categories": categories,
        "self_evaluation_scores": self_evals,
    }


