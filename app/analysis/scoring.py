from __future__ import annotations

from app.services import LLMAnalysisResult


def determine_importance_score(llm_output: LLMAnalysisResult) -> float:
    """
    LLMの分析結果から重要度スコアを決定する。
    スコアが存在しない場合は重要度ラベルから算出し、どちらも無ければ0.0を返す。

    Args:
        llm_output: LLMからの分析結果

    Returns:
        重要度スコア (0.0 ~ 1.0)
    """
    if llm_output.importance_level:
        if llm_output.importance_level == "high":
            return 1.0
        if llm_output.importance_level == "medium":
            return 0.5
        if llm_output.importance_level == "low":
            return 0.0

    if llm_output.importance_score is not None:
        score = float(llm_output.importance_score)
        return max(0.0, min(1.0, score))

    return 0.0
