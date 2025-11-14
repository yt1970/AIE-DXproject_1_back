from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db

router = APIRouter()


def _choose_effective_files(
    rows: Iterable[models.UploadedFile],
) -> Dict[int, models.UploadedFile]:
    """
    For each lecture_number, choose one file:
      - Prefer finalized (finalized_at not null), pick the most recent finalized_at
      - Otherwise pick the most recent upload_timestamp
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
    """
    Build SQLAlchemy filter expression for Comment.analysis_version by version.
    - version == "final" -> analysis_version == "final"
    - version == "preliminary" -> analysis_version == "preliminary" OR NULL
    - version is None -> no filter (use all available)
    """
    if version == "final":
        return models.Comment.analysis_version == "final"
    if version == "preliminary":
        return or_(
            models.Comment.analysis_version == "preliminary",
            models.Comment.analysis_version.is_(None),
        )
    return None


def _compute_average_scores(db: Session, file_ids: List[int]) -> Dict[str, Optional[float]]:
    if not file_ids:
        return {}
    s = (
        db.query(
            func.avg(models.SurveyResponse.score_satisfaction_overall),
            func.avg(models.SurveyResponse.score_satisfaction_content_volume),
            func.avg(models.SurveyResponse.score_satisfaction_content_understanding),
            func.avg(models.SurveyResponse.score_satisfaction_instructor_overall),
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
        "instructor_overall": _maybe_round(s[3]),
        "self_preparation": _maybe_round(s[4]),
        "self_motivation": _maybe_round(s[5]),
        "self_applicability": _maybe_round(s[6]),
    }


def _maybe_round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _compute_nps(db: Session, file_ids: List[int]) -> Dict[str, float]:
    if not file_ids:
        return {"score": 0.0, "promoters_percent": 0.0, "detractors_percent": 0.0}
    rows = (
        db.query(models.SurveyResponse.score_recommend_to_friend)
        .filter(models.SurveyResponse.file_id.in_(file_ids))
        .all()
    )
    scores = [r[0] for r in rows if r[0] is not None]
    if not scores:
        return {"score": 0.0, "promoters_percent": 0.0, "detractors_percent": 0.0}
    total = len(scores)
    promoters = sum(1 for v in scores if v == 5)
    detractors = sum(1 for v in scores if v in (1, 2))
    promoters_pct = round(promoters * 100.0 / total, 1)
    detractors_pct = round(detractors * 100.0 / total, 1)
    nps = round(promoters_pct - detractors_pct, 1)
    return {
        "score": nps,
        "promoters_percent": promoters_pct,
        "detractors_percent": detractors_pct,
    }


def _compute_nps_for_file(db: Session, file_id: int) -> float:
    data = _compute_nps(db, [file_id])
    return data["score"]


def _response_count(db: Session, file_id: int) -> int:
    return (
        db.query(models.SurveyResponse)
        .filter(models.SurveyResponse.file_id == file_id)
        .count()
    )


def _sentiment_breakdown(
    db: Session, file_ids: List[int], version: Optional[str]
) -> Dict[str, int]:
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
    db: Session = Depends(get_db),
) -> dict:
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
    nps = _compute_nps(db, chosen_ids)

    nps_transition = []
    response_count_transition = []
    for lecture_num, f in sorted(chosen.items(), key=lambda x: x[0]):
        nps_transition.append(
            {"lecture_num": lecture_num, "score": _compute_nps_for_file(db, f.file_id)}
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


@router.get("/dashboard/{lecture_id}/yearly")
def dashboard_yearly(
    lecture_id: int,
    version: Optional[str] = Query(default="final", enum=["final", "preliminary"]),
    db: Session = Depends(get_db),
) -> dict:
    lecture = db.query(models.Lecture).filter(models.Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    same_course_lectures = (
        db.query(models.Lecture)
        .filter(models.Lecture.course_name == lecture.course_name)
        .order_by(models.Lecture.academic_year.asc())
        .all()
    )

    results: List[dict] = []
    for lec in same_course_lectures:
        files = (
            db.query(models.UploadedFile)
            .filter(models.UploadedFile.lecture_id == lec.id)
            .all()
        )
        if not files:
            results.append(
                {
                    "academic_year": lec.academic_year,
                    "average_scores": {},
                    "nps": {"score": 0.0, "promoters_percent": 0.0, "detractors_percent": 0.0},
                    "response_count": 0,
                }
            )
            continue
        chosen = _choose_effective_files(files)
        chosen_ids = [f.file_id for f in chosen.values()]
        avg_scores = _compute_average_scores(db, chosen_ids)
        nps = _compute_nps(db, chosen_ids)
        responses = (
            db.query(models.SurveyResponse)
            .filter(models.SurveyResponse.file_id.in_(chosen_ids))
            .count()
        )
        results.append(
            {
                "academic_year": lec.academic_year,
                "average_scores": avg_scores,
                "nps": nps,
                "response_count": int(responses),
            }
        )

    return {"course_name": lecture.course_name, "yearly": results}


