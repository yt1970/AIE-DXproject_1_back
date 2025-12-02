from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.analysis import (
    OverallTrendsResponse,
    YearComparisonResponse,
    LectureInfoItem,
    ResponseTrendItem,
    ParticipationTrendItem,
    NPSSummary,
    NPSTrendItem,
    ScoreTrendItem,
    OverallAverages,
    SentimentSummaryItem,
    CategorySummaryItem,
    ScoreItem,
    YearMetrics,
    ScoreComparisonItem,
    Sentiment,
    CommentCategory,
)
from collections import defaultdict

router = APIRouter()

@router.get("/courses/trends", response_model=OverallTrendsResponse)
def get_overall_trends(
    name: str = Query(..., description="講座名"),
    academic_year: int = Query(..., description="年度"),
    term: str = Query(..., description="期間"),
    batch_type: str = Query(..., description="preliminary/confirmed"),
    student_attribute: str = Query("all", description="属性フィルタ"),
    db: Session = Depends(get_db),
) -> OverallTrendsResponse:
    """
    講座全体を通しての傾向データを取得する。
    """
    # 1. 対象講座の講義回一覧を取得
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
        # Return empty structure if no course found
        return OverallTrendsResponse(
            lecture_info=[],
            response_trends=[],
            participation_trends=[],
            nps_summary=NPSSummary(
                score=0.0, promoters_count=0, promoters_percentage=0.0,
                neutrals_count=0, neutrals_percentage=0.0,
                detractors_count=0, detractors_percentage=0.0, total_responses=0
            ),
            nps_trends=[],
            score_trends=[],
            overall_averages=OverallAverages(
                overall={"label": "総合満足度", "items": []},
                content={"label": "講義内容", "items": []},
                instructor={"label": "講師評価", "items": []},
                self_evaluation={"label": "受講生の自己評価", "items": []}
            ),
            sentiment_summary=[],
            category_summary=[]
        )

    lecture_ids = [l.id for l in lectures]
    
    # 2. 各講義回のバッチを取得 (指定されたbatch_typeの最新)
    batches = []
    for lec in lectures:
        b = (
            db.query(models.SurveyBatch)
            .filter(
                models.SurveyBatch.lecture_id == lec.id,
                models.SurveyBatch.batch_type == batch_type
            )
            .order_by(models.SurveyBatch.uploaded_at.desc())
            .first()
        )
        if b:
            batches.append(b)

    batch_ids = [b.id for b in batches]
    
    # 3. サマリデータを取得
    query = db.query(models.SurveySummary).filter(
        models.SurveySummary.survey_batch_id.in_(batch_ids)
    )
    
    if student_attribute != 'all':
        query = query.filter(models.SurveySummary.student_attribute == student_attribute)
    
    summaries = query.all()
    
    # Map for main stats (if 'all', we use 'all' summary, else specific)
    # If student_attribute is 'all', we need to pick the 'all' summary for the main stats
    # and use others for breakdown.
    summary_map = {}
    for s in summaries:
        if s.student_attribute == student_attribute:
            summary_map[s.survey_batch_id] = s
            
    # Calculate first lecture response count for retention rate
    first_lecture_response_count = 0
    first_lecture_id = lecture_ids[0] if lecture_ids else None
    
    if first_lecture_id:
        # Find batch for first lecture
        first_batch = next((b for b in batches if b.lecture_id == first_lecture_id), None)
        if first_batch:
            # Find summary for first batch matching the requested attribute
            first_summary = next((s for s in summaries if s.survey_batch_id == first_batch.id and s.student_attribute == student_attribute), None)
            if first_summary:
                first_lecture_response_count = first_summary.response_count

    # 4. データ構築
    
    # Lecture Info
    lecture_info_items = [
        LectureInfoItem(
            lecture_id=l.id,
            session=l.session,
            lecture_date=str(l.lecture_on),
            instructor_name=l.instructor_name,
            description=l.description
        ) for l in lectures
    ]

    # Trends
    response_trends = []
    participation_trends = []
    nps_trends = []
    score_trends = []
    
    # Aggregators for overall averages
    total_scores = defaultdict(list) # key -> list of scores
    
    # Aggregators for NPS
    total_promoters = 0
    total_neutrals = 0
    total_detractors = 0
    total_responses_nps = 0

    for lec in lectures:
        # Find batch for this lecture
        batch = next((b for b in batches if b.lecture_id == lec.id), None)
        summary = summary_map.get(batch.id) if batch else None
        
        # Response Trend
        resp_count = summary.response_count if summary else 0
        
        # Retention Rate Calculation
        # 第1回を100%として計算
        retention = 0.0
        if first_lecture_response_count > 0:
            retention = (resp_count / first_lecture_response_count) * 100.0
        elif lec.id == first_lecture_id and resp_count > 0:
             # If this is the first lecture and count > 0, it's 100%
             retention = 100.0

        # Breakdown (only if student_attribute='all')
        breakdown_data = None
        if student_attribute == 'all' and batch:
            # Filter summaries for this batch
            batch_summaries = [s for s in summaries if s.survey_batch_id == batch.id]
            breakdown_data = {
                "student": 0,
                "corporate": 0,
                "invited": 0,
                "faculty": 0,
                "other": 0
            }
            for s in batch_summaries:
                if s.student_attribute == 'student':
                    breakdown_data["student"] = s.response_count
                elif s.student_attribute == 'corporate':
                    breakdown_data["corporate"] = s.response_count
                elif s.student_attribute == 'invited':
                    breakdown_data["invited"] = s.response_count
                elif s.student_attribute == 'faculty':
                    breakdown_data["faculty"] = s.response_count
                elif s.student_attribute == 'other':
                    breakdown_data["other"] = s.response_count

        response_trends.append(ResponseTrendItem(
            session=lec.session,
            response_count=resp_count,
            retention_rate=round(retention, 1),
            breakdown=breakdown_data
        ))
        
        # Participation Trend
        participation_trends.append(ParticipationTrendItem(
            session=lec.session,
            zoom_participants=batch.zoom_participants if batch else None,
            recording_views=batch.recording_views if batch else None
        ))
        
        # NPS Trend
        nps_score = float(summary.nps) if summary and summary.nps is not None else 0.0
        nps_trends.append(NPSTrendItem(session=lec.session, nps_score=nps_score))
        
        if summary:
            total_promoters += summary.promoter_count
            total_neutrals += summary.passive_count
            total_detractors += summary.detractor_count
            total_responses_nps += summary.response_count
            
            # Score Trend
            scores_dict = {
                "overall_satisfaction": float(summary.avg_satisfaction_overall or 0),
                "learning_amount": float(summary.avg_content_volume or 0),
                "comprehension": float(summary.avg_content_understanding or 0),
                "operations": float(summary.avg_content_announcement or 0),
                "instructor_satisfaction": float(summary.avg_instructor_overall or 0),
                "time_management": float(summary.avg_instructor_time or 0),
                "question_handling": float(summary.avg_instructor_qa or 0),
                "speaking_style": float(summary.avg_instructor_speaking or 0),
                "preparation": float(summary.avg_self_preparation or 0),
                "motivation": float(summary.avg_self_motivation or 0),
                "future_application": float(summary.avg_self_future or 0),
            }
            score_trends.append(ScoreTrendItem(session=lec.session, scores=scores_dict))
            
            # Accumulate for overall average
            for k, v in scores_dict.items():
                if v > 0: total_scores[k].append(v)
        else:
            score_trends.append(ScoreTrendItem(
                session=lec.session, 
                scores={k: 0.0 for k in [
                    "overall_satisfaction", "learning_amount", "comprehension", "operations",
                    "instructor_satisfaction", "time_management", "question_handling", "speaking_style",
                    "preparation", "motivation", "future_application"
                ]}
            ))

    # Overall NPS
    overall_nps_score = 0.0
    if total_responses_nps > 0:
        overall_nps_score = ((total_promoters - total_detractors) / total_responses_nps) * 100.0
    
    nps_summary = NPSSummary(
        score=round(overall_nps_score, 1),
        promoters_count=total_promoters,
        promoters_percentage=round(total_promoters/total_responses_nps*100, 1) if total_responses_nps else 0,
        neutrals_count=total_neutrals,
        neutrals_percentage=round(total_neutrals/total_responses_nps*100, 1) if total_responses_nps else 0,
        detractors_count=total_detractors,
        detractors_percentage=round(total_detractors/total_responses_nps*100, 1) if total_responses_nps else 0,
        total_responses=total_responses_nps
    )

    # Overall Averages
    def _avg(key):
        vals = total_scores[key]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    overall_averages = OverallAverages(
        overall={"label": "総合満足度", "items": [ScoreItem(name="本日の総合的な満足度", score=_avg("overall_satisfaction"))]},
        content={"label": "講義内容", "items": [
            ScoreItem(name="講義内容の学習量", score=_avg("learning_amount")),
            ScoreItem(name="講義内容の理解度", score=_avg("comprehension")),
            ScoreItem(name="講義中の運営アナウンス", score=_avg("operations")),
        ]},
        instructor={"label": "講師評価", "items": [
            ScoreItem(name="講師の総合的な満足度", score=_avg("instructor_satisfaction")),
            ScoreItem(name="講師の授業時間の使い方", score=_avg("time_management")),
            ScoreItem(name="講師の質問対応", score=_avg("question_handling")),
            ScoreItem(name="講師の話し方", score=_avg("speaking_style")),
        ]},
        self_evaluation={"label": "受講生の自己評価", "items": [
            ScoreItem(name="自身の予習", score=_avg("preparation")),
            ScoreItem(name="自身の意欲", score=_avg("motivation")),
            ScoreItem(name="自身の今後への活用", score=_avg("future_application")),
        ]}
    )

    # Sentiment & Category Summary (Aggregation from CommentSummary)
    # Note: CommentSummary stores count per batch. We sum them up.
    comment_summaries = (
        db.query(models.CommentSummary)
        .filter(
            models.CommentSummary.survey_batch_id.in_(batch_ids),
            models.CommentSummary.student_attribute == student_attribute
        )
        .all()
    )
    
    sentiments = defaultdict(int)
    categories = defaultdict(int)
    total_comments = 0
    
    for cs in comment_summaries:
        if cs.analysis_type == 'sentiment':
            sentiments[cs.label] += cs.count
            total_comments += cs.count # This might double count if we sum both types? 
            # Actually sentiment covers all comments usually.
        elif cs.analysis_type == 'category':
            categories[cs.label] += cs.count

    # Recalculate total for percentage based on sentiment counts
    total_sentiments = sum(sentiments.values())
    
    sentiment_summary = []
    for s_key in ["positive", "neutral", "negative"]:
        cnt = sentiments.get(s_key, 0)
        pct = (cnt / total_sentiments * 100.0) if total_sentiments > 0 else 0.0
        sentiment_summary.append(SentimentSummaryItem(
            sentiment=Sentiment(s_key), count=cnt, percentage=round(pct, 1)
        ))

    category_summary = []
    for c_key in ["content", "materials", "operations", "instructor", "other"]:
        # Map DB label to Enum if needed, assuming match
        # DB label might be 'material' singular? Check models.
        # models.CategoryType has 'material', 'operation'.
        # Schema has 'materials', 'operations'.
        # Need mapping.
        db_key = c_key
        if c_key == 'materials': db_key = 'material'
        if c_key == 'operations': db_key = 'operation'
        
        cnt = categories.get(db_key, 0)
        category_summary.append(CategorySummaryItem(
            category=CommentCategory(c_key), count=cnt
        ))

    return OverallTrendsResponse(
        lecture_info=lecture_info_items,
        response_trends=response_trends,
        participation_trends=participation_trends,
        nps_summary=nps_summary,
        nps_trends=nps_trends,
        score_trends=score_trends,
        overall_averages=overall_averages,
        sentiment_summary=sentiment_summary,
        category_summary=category_summary
    )

@router.get("/courses/compare", response_model=YearComparisonResponse)
def compare_years(
    name: str = Query(..., description="講座名"),
    current_year: int = Query(..., description="比較元の年度"),
    current_term: str = Query(..., description="比較元の期間"),
    compare_year: int = Query(..., description="比較先の年度"),
    compare_term: str = Query(..., description="比較先の期間"),
    batch_type: str = Query(..., description="分析タイプ"),
    db: Session = Depends(get_db),
) -> YearComparisonResponse:
    """
    同一講座名の異なる年度・期間のデータを比較する。
    """
    # Helper to calculate metrics for a specific period
    def _get_metrics(t_year: int, t_term: str) -> tuple[YearMetrics, List[NPSTrendItem]]:
        # 1. Get Lectures
        lectures = (
            db.query(models.Lecture)
            .filter(
                models.Lecture.name == name,
                models.Lecture.academic_year == t_year,
                models.Lecture.term == t_term,
            )
            .order_by(models.Lecture.lecture_on)
            .all()
        )
        
        if not lectures:
            return YearMetrics(
                academic_year=t_year, term=t_term, total_responses=0, session_count=0,
                average_nps=0.0, average_scores={}
            ), []

        lecture_ids = [l.id for l in lectures]
        
        # 2. Get Batches
        batches = []
        for lec in lectures:
            b = (
                db.query(models.SurveyBatch)
                .filter(
                    models.SurveyBatch.lecture_id == lec.id,
                    models.SurveyBatch.batch_type == batch_type
                )
                .order_by(models.SurveyBatch.uploaded_at.desc())
                .first()
            )
            if b: batches.append(b)
            
        batch_ids = [b.id for b in batches]
        
        # 3. Get Summaries
        summaries = (
            db.query(models.SurveySummary)
            .filter(
                models.SurveySummary.survey_batch_id.in_(batch_ids),
                models.SurveySummary.student_attribute == "all" # Compare uses 'all' implicitly? Spec doesn't say, assume all.
            )
            .all()
        )
        summary_map = {s.survey_batch_id: s for s in summaries}

        # 4. Aggregation
        total_responses = 0
        total_promoters = 0
        total_neutrals = 0
        total_detractors = 0
        
        score_lists = defaultdict(list)
        nps_trends_list = []
        
        for lec in lectures:
            batch = next((b for b in batches if b.lecture_id == lec.id), None)
            summary = summary_map.get(batch.id) if batch else None
            
            nps_val = float(summary.nps) if summary and summary.nps is not None else 0.0
            nps_trends_list.append(NPSTrendItem(session=lec.session, nps_score=nps_val))
            
            if summary:
                total_responses += summary.response_count
                total_promoters += summary.promoter_count
                total_neutrals += summary.passive_count
                total_detractors += summary.detractor_count
                
                # Scores
                s_map = {
                    "overall_satisfaction": summary.avg_satisfaction_overall,
                    "learning_amount": summary.avg_content_volume,
                    "comprehension": summary.avg_content_understanding,
                    "operations": summary.avg_content_announcement,
                    "instructor_satisfaction": summary.avg_instructor_overall,
                    "time_management": summary.avg_instructor_time,
                    "question_handling": summary.avg_instructor_qa,
                    "speaking_style": summary.avg_instructor_speaking,
                    "preparation": summary.avg_self_preparation,
                    "motivation": summary.avg_self_motivation,
                    "future_application": summary.avg_self_future,
                }
                for k, v in s_map.items():
                    if v is not None:
                        score_lists[k].append(float(v))

        # Averages
        avg_nps = 0.0
        if total_responses > 0:
            avg_nps = ((total_promoters - total_detractors) / total_responses) * 100.0
            
        avg_scores = {}
        all_keys = [
            "overall_satisfaction", "learning_amount", "comprehension", "operations",
            "instructor_satisfaction", "time_management", "question_handling", "speaking_style",
            "preparation", "motivation", "future_application"
        ]
        for k in all_keys:
            vals = score_lists[k]
            avg_scores[k] = round(sum(vals) / len(vals), 2) if vals else 0.0
            
        metrics = YearMetrics(
            academic_year=t_year,
            term=t_term,
            total_responses=total_responses,
            session_count=len(lectures),
            average_nps=round(avg_nps, 1),
            average_scores=avg_scores
        )
        return metrics, nps_trends_list

    current_metrics, current_trends = _get_metrics(current_year, current_term)
    compare_metrics, compare_trends = _get_metrics(compare_year, compare_term)
    
    # Score Comparison
    score_comparisons = []
    # Map keys to Japanese labels
    label_map = {
        "overall_satisfaction": "総合満足度",
        "learning_amount": "学習量",
        "comprehension": "理解度",
        "operations": "運営",
        "instructor_satisfaction": "講師満足度",
        "time_management": "時間使い方",
        "question_handling": "質問対応",
        "speaking_style": "話し方",
        "preparation": "予習",
        "motivation": "意欲",
        "future_application": "今後活用"
    }
    
    for k, label in label_map.items():
        curr = current_metrics.average_scores.get(k, 0.0)
        comp = compare_metrics.average_scores.get(k, 0.0)
        diff = round(curr - comp, 2)
        score_comparisons.append(ScoreComparisonItem(
            category=label,
            category_key=k,
            current_score=curr,
            comparison_score=comp,
            difference=diff
        ))

    return YearComparisonResponse(
        current=current_metrics,
        comparison=compare_metrics,
        nps_trends={"current": current_trends, "comparison": compare_trends},
        score_comparison=score_comparisons
    )
