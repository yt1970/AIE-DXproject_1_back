from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.db.models import SentimentType
from app.services import LLMAnalysisResult as LLMStructuredResult
from app.services import (
    LLMClient,
    LLMClientConfig,
    LLMClientError,
    build_default_llm_config,
)

from . import aggregation, safety, scoring

logger = logging.getLogger(__name__)


class CommentAnalysisResult:
    """コメント分析結果を格納するコンテナ。"""

    def __init__(
        self,
        is_improvement_needed: bool,
        is_slanderous: bool,
        sentiment: str,
        sentiment_normalized: SentimentType,
        *,
        category: Optional[str] = None,
        summary: Optional[str] = None,
        importance_level: Optional[str] = None,
        importance_score: Optional[float] = None,
        risk_level: Optional[str] = None,
        warnings: Optional[List[str]] = None,
        raw_llm: Optional[Dict[str, Any]] = None,
    ) -> None:
        # DBのCommentAnalysisモデルと対応する属性
        self.is_improvement_needed = is_improvement_needed
        self.is_slanderous = is_slanderous
        self.sentiment = sentiment
        self.sentiment_normalized = sentiment_normalized

        # LLM分析結果の詳細情報
        self.category = category
        self.summary = summary
        self.importance_level = importance_level
        self.importance_score = importance_score
        self.risk_level = risk_level

        # デバッグやログ用の追加情報
        self.warnings = warnings or []
        self.raw_llm = raw_llm or {}

    def __repr__(self) -> str:
        return (
            "CommentAnalysisResult("
            f"is_improvement_needed={self.is_improvement_needed}, "
            f"is_slanderous={self.is_slanderous}, "
            f"sentiment={self.sentiment_normalized.value}"
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

    # --- 各種分析ロジックを呼び出し、最終的な判定を行う ---
    # is_improvement_needed: LLMの出力やキーワードに基づいて改善要否を判定
    # (注: ここはビジネスロジックに合わせてより高度な判定が可能です)
    is_improvement_needed = (
        "改善" in comment_text or (llm_structured.importance_score or 0) > 0.7
    )

    # is_slanderous: 安全性チェックモジュールで誹謗中傷を判定
    is_slanderous = not safety.is_comment_safe(comment_text, llm_structured)

    category_guess, sentiment_guess = aggregation.classify_comment(
        comment_text, llm_structured
    )

    final_category = llm_structured.category or category_guess
    final_summary = llm_structured.summary or _fallback_summary(comment_text)
    final_importance_level = llm_structured.importance_level or "low"
    final_importance_score = (
        llm_structured.importance_score
        if llm_structured.importance_score is not None
        else 0.0
    )
    final_risk_level = llm_structured.risk_level or "none"
    sentiment_enum = _normalize_sentiment(llm_structured.sentiment or sentiment_guess)
    sentiment_label = SENTIMENT_DISPLAY[sentiment_enum]

    combined_warnings = _dedupe_warnings(llm_warnings + llm_structured.warnings)

    return CommentAnalysisResult(
        is_improvement_needed=is_improvement_needed,
        is_slanderous=is_slanderous,
        sentiment=sentiment_label,
        sentiment_normalized=sentiment_enum,
        category=final_category,
        summary=final_summary,
        importance_level=final_importance_level,
        importance_score=final_importance_score,
        risk_level=final_risk_level,
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


SENTIMENT_ALIASES = {
    "positive": SentimentType.positive,
    "ポジティブ": SentimentType.positive,
    "negative": SentimentType.negative,
    "ネガティブ": SentimentType.negative,
    "neutral": SentimentType.neutral,
    "ニュートラル": SentimentType.neutral,
}

SENTIMENT_DISPLAY = {
    SentimentType.positive: "ポジティブ",
    SentimentType.negative: "ネガティブ",
    SentimentType.neutral: "ニュートラル",
}


def _normalize_sentiment(raw_value: str | None) -> SentimentType:
    """Map arbitrary sentiment labels to the Enum we persist."""
    if not raw_value:
        return SentimentType.neutral

    normalized = raw_value.strip().lower()
    if normalized in SentimentType.__members__:
        return SentimentType[normalized]

    # Japanese labels and other aliases are matched without lower-casing
    if raw_value in SENTIMENT_ALIASES:
        return SENTIMENT_ALIASES[raw_value]

    for key, mapped in SENTIMENT_ALIASES.items():
        if key.lower() == normalized:
            return mapped

    return SentimentType.neutral
