from __future__ import annotations

from typing import Dict, List

from app.services import LLMAnalysisResult


def calculate_importance_score(
    comment_text: str, llm_output: LLMAnalysisResult
) -> float:
    """
    コメントの重要度スコアを計算する。

    Args:
        comment_text: コメント文字列
        llm_output: LLMからの分析結果

    Returns:
        重要度スコア (0.0 ~ 1.0)
    """
    if llm_output.importance_score is not None:
        return float(max(0.0, min(1.0, llm_output.importance_score)))

    normalized_level = (llm_output.importance_level or "").lower()
    level_to_score = {
        "critical": 1.0,
        "very_high": 1.0,
        "very high": 1.0,
        "urgent": 0.9,
        "high": 0.8,
        "medium": 0.6,
        "normal": 0.5,
        "low": 0.3,
        "minor": 0.2,
    }
    if normalized_level in level_to_score:
        return level_to_score[normalized_level]

    # Fallback: コメントの長さを用いた簡易スコアリング
    length_score = min(len(comment_text) / 400.0, 1.0)
    return round(length_score, 3)


def rank_comments(comments: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    スコアに基づいてコメントのリストをランキングする。
    """
    return sorted(comments, key=lambda c: float(c.get("score", 0.0)), reverse=True)
