from __future__ import annotations

import logging
from typing import Optional

from app.services import LLMAnalysisResult, LLMClient, LLMClientError

logger = logging.getLogger(__name__)


def analyze_with_llm(
    llm_client: LLMClient,
    comment_text: str,
    *,
    course_name: Optional[str] = None,
    question_text: Optional[str] = None,
) -> LLMAnalysisResult:
    """
    LLMを使用してコメントを多角的に分析し、結果を統合して返す。
    """
    try:
        return llm_client.analyze_comment(
            comment_text,
            analysis_type="full_analysis",
            course_name=course_name,
            question_text=question_text,
        )
    except (LLMClientError, ValueError) as exc:
        warning = f"LLM analysis for 'full_analysis' failed: {exc}"
        logger.warning(warning)
        return LLMAnalysisResult(
            raw={"full_analysis": {"error": str(exc)}}, warnings=[warning]
        )
