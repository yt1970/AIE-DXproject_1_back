from __future__ import annotations

from app.services import LLMAnalysisResult

# NGワードリスト (例)
NG_WORDS = ["不適切", "誹謗中傷", "差別"]


def is_comment_safe(comment_text: str, llm_output: LLMAnalysisResult) -> bool:
    """
    LLMの出力やNGワードリストに基づき、コメントが安全かどうかを判定する。
    """
    if any(word in comment_text for word in NG_WORDS):
        return False

    if llm_output.is_safe is not None and llm_output.is_safe is False:
        return False

    risk_level = (llm_output.risk_level or "").lower()
    if risk_level in {"high", "critical", "severe", "危険"}:
        return False

    return True
