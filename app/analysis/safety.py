from __future__ import annotations

from app.services import LLMAnalysisResult


def is_comment_safe(comment_text: str, llm_output: LLMAnalysisResult) -> bool:
    """
    LLMの分析結果に基づき、コメントが安全かどうかを判定する。
    """
    if llm_output.is_safe is not None and llm_output.is_safe is False:
        return False

    risk_level = (llm_output.risk_level or "").lower()
    if risk_level in {"high", "critical", "severe", "危険"}:
        return False

    return True


def get_higher_risk_level(level1: str | None, level2: str | None) -> str:
    """2つのリスクレベルを比較し、より高い方を返す。"""
    order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    level1_norm = (level1 or "none").lower()
    level2_norm = (level2 or "none").lower()
    return max(level1_norm, level2_norm, key=lambda x: order.get(x, 0))
