from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.services import (
    build_default_llm_config,
    LLMAnalysisResult as LLMStructuredResult,
    LLMClient,
    LLMClientConfig,
    LLMClientError,
)

from . import aggregation, safety, scoring

logger = logging.getLogger(__name__)


class CommentAnalysisResult:
    """コメント分析結果を格納するコンテナ。"""

    def __init__(
        self,
        score: float,
        category: str,
        sentiment: str,
        is_safe: bool,
        *,
        importance_level: Optional[str] = None,
        importance_score: Optional[float] = None,
        risk_level: Optional[str] = None,
        summary: Optional[str] = None,
        warnings: Optional[List[str]] = None,
        raw_llm: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.score = score
        # LLMのスコアが別途存在する場合は優先し、なければscoreを流用
        self.importance_score = (
            importance_score if importance_score is not None else score
        )
        self.category = category
        self.sentiment = sentiment
        self.is_safe = is_safe
        self.importance_level = importance_level
        self.risk_level = risk_level
        self.summary = summary
        self.warnings = warnings or []
        self.raw_llm = raw_llm or {}

    def __repr__(self) -> str:
        return (
            "CommentAnalysisResult("
            f"score={self.score}, "
            f"category='{self.category}', "
            f"sentiment='{self.sentiment}', "
            f"is_safe={self.is_safe}, "
            f"importance_level={self.importance_level}, "
            f"risk_level={self.risk_level}"
            ")"
        )


@lru_cache
def get_llm_client() -> LLMClient:
    """環境変数から設定を読み込み、LLMクライアントを初期化する。"""
    config = build_default_llm_config()
    try:
        return LLMClient(config=config)
    except ValueError as exc:
        logger.warning(
            "Invalid LLM configuration detected (%s); falling back to mock provider.",
            exc,
        )
        return LLMClient(config=LLMClientConfig(provider="mock"))


def analyze_comment(comment_text: str) -> CommentAnalysisResult:
    """
    単一のコメントを分析し、総合的な結果を返す

    Args:
        comment_text: 分析対象のコメント文字列

    Returns:
        分析結果をまとめたオブジェクト
    """

    llm_warnings: List[str] = []
    try:
        llm_structured = get_llm_client().analyze_comment(comment_text)
    except (LLMClientError, ValueError) as exc:
        warning = f"LLM analysis failed: {exc}"
        logger.warning(warning)
        llm_warnings.append(warning)
        llm_structured = LLMStructuredResult(
            raw={"error": str(exc), "comment": comment_text},
            warnings=[warning],
        )

    importance_score = scoring.calculate_importance_score(
        comment_text, llm_structured
    )
    category, sentiment = aggregation.classify_comment(comment_text, llm_structured)
    is_safe = safety.is_comment_safe(comment_text, llm_structured)
    risk_level = llm_structured.risk_level or ("high" if not is_safe else "none")
    summary = llm_structured.summary or _fallback_summary(comment_text)

    combined_warnings = _dedupe_warnings(llm_warnings + llm_structured.warnings)

    return CommentAnalysisResult(
        score=importance_score,
        category=category,
        sentiment=sentiment,
        is_safe=is_safe,
        importance_level=llm_structured.importance_level,
        importance_score=llm_structured.importance_score,
        risk_level=risk_level,
        summary=summary,
        warnings=combined_warnings,
        raw_llm=llm_structured.raw,
    )


def _dedupe_warnings(warnings: List[str]) -> List[str]:
    """重複する警告メッセージを順序を保ったまま削除する。"""
    seen = set()
    deduped: List[str] = []
    for warning in warnings:
        if warning not in seen:
            deduped.append(warning)
            seen.add(warning)
    return deduped


def _fallback_summary(comment_text: str, limit: int = 120) -> str:
    """LLMが要約を返さなかった場合のフォールバック要約。"""
    normalized = comment_text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)] + "..."
