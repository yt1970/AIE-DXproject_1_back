from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from app.db.models import SentimentType
from app.services import LLMClient, LLMClientConfig, build_default_llm_config

from . import aggregation, llm_analyzer, safety, scoring

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
        llm_result: llm_analyzer.LLMAnalysisResult,
    ) -> None:
        # DBのCommentAnalysisモデルと対応する属性
        self.is_improvement_needed = is_improvement_needed
        self.is_slanderous = is_slanderous
        self.sentiment = sentiment
        self.sentiment_normalized = sentiment_normalized

        # LLM分析結果の詳細情報
        self.category = llm_result.category
        self.summary = llm_result.summary
        self.importance_level = llm_result.importance_level
        self.importance_score = llm_result.importance_score
        self.risk_level = llm_result.risk_level

        # デバッグやログ用の追加情報
        self.warnings = llm_result.warnings
        self.raw_llm = llm_result.raw

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

    # mockプロバイダーの場合は、設定不備があっても常に動作させる
    if config.provider == "mock":
        return LLMClient(config=LLMClientConfig(provider="mock"))

    # mock以外のプロバイダーで設定不備がある場合は、警告を出してフォールバックする
    try:
        return LLMClient(config=config)
    except ValueError as exc:
        logger.warning(
            "Invalid LLM configuration for provider '%s' (%s); falling back to mock provider.",
            config.provider,
            exc,
        )
        return LLMClient(config=LLMClientConfig(provider="mock"))


def analyze_comment(
    comment_text: str,
    *,
    course_name: Optional[str] = None,
    question_text: Optional[str] = None,
    skip_llm_analysis: bool = False,
) -> CommentAnalysisResult:
    """
    単一のコメントを分析し、総合的な結果を返す
    """

    # --- 1. 各種分析モジュールを呼び出す ---
    # skip_llm_analysisフラグがTrueの場合、LLMを呼び出さずにデフォルト値を返す
    if skip_llm_analysis:
        llm_structured = llm_analyzer.LLMAnalysisResult(
            raw={"skipped": True, "reason": "Not a target for LLM analysis"},
            warnings=["LLM analysis was skipped for this comment."],
        )
    else:
        llm_client = get_llm_client()
        llm_structured = llm_analyzer.analyze_with_llm(
            llm_client, comment_text, course_name=course_name, question_text=question_text
        )

    # 将来的にはここに形態素解析などの結果も追加できる
    # morphological_result = morphological_analyzer.analyze(...)

    # --- 各種分析ロジックを呼び出し、最終的な判定を行う ---
    final_importance_score = scoring.determine_importance_score(llm_structured)
    is_improvement_needed = final_importance_score > 0.7

    # is_slanderous: 安全性チェックモジュールで誹謗中傷を判定
    is_slanderous = not safety.is_comment_safe(comment_text, llm_structured)

    category_guess, sentiment_guess = aggregation.classify_comment(
        comment_text, llm_structured
    )

    sentiment_enum = _normalize_sentiment(llm_structured.sentiment or sentiment_guess)
    sentiment_label = SENTIMENT_DISPLAY[sentiment_enum]

    # 最終的な結果を構築
    llm_structured.importance_score = final_importance_score
    llm_structured.risk_level = llm_structured.risk_level or "none"
    llm_structured.category = llm_structured.category or category_guess
    llm_structured.summary = llm_structured.summary or _fallback_summary(comment_text)

    return CommentAnalysisResult(
        is_improvement_needed=is_improvement_needed,
        is_slanderous=is_slanderous,
        sentiment=sentiment_label,
        sentiment_normalized=sentiment_enum,
        llm_result=llm_structured,
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
