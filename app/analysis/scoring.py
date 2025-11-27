from __future__ import annotations

from app.services import LLMAnalysisResult


def determine_importance_score(llm_output: LLMAnalysisResult) -> float:
    """
    LLMの分析結果から重要度スコアを決定する。
    スコアが存在しない場合は0.0を返す。

    Args:
        llm_output: LLMからの分析結果

    Returns:
        重要度スコア (0.0 ~ 1.0)
    """
    if llm_output.importance_score is not None:
        # Scoreの算出は、high: 1.0, medium: 0.5, low: 0.0とする。
        if llm_output.importance_level == "high":
            return 1.0
        elif llm_output.importance_level == "medium":
            return 0.5
        elif llm_output.importance_level == "low":
            return 0.0
    return 0.0
