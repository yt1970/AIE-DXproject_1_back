from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from app.db.models import CategoryType, ImportanceType, RiskLevelType, SentimentType
from app.services import LLMClient, LLMClientConfig, build_default_llm_config

from . import aggregation, llm_analyzer, safety, scoring

logger = logging.getLogger(__name__)


class CommentAnalysisResult:
    """コメント分析結果を格納するコンテナ。"""

    def __init__(
        self,
        is_improvement_needed: bool,
        is_abusive: bool,
        sentiment_normalized: SentimentType,
        *,
        llm_result: llm_analyzer.LLMAnalysisResult,
        risk_level_normalized: RiskLevelType,
        category_normalized: CategoryType,
        importance_normalized: ImportanceType | None,
    ) -> None:
        # DBのCommentAnalysisモデルと対応する属性
        self.is_improvement_needed = is_improvement_needed
        self.is_abusive = is_abusive
        self.sentiment_normalized = sentiment_normalized
        # LLM分析結果の詳細情報
        self.category_normalized = category_normalized
        self.summary = llm_result.summary
        self.importance_normalized = importance_normalized
        self.importance_score = llm_result.importance_score
        self.risk_level_normalized = risk_level_normalized

        # デバッグやログ用の追加情報
        self.warnings = llm_result.warnings
        self.raw_llm = llm_result.raw

    @property
    def sentiment(self) -> str:
        return self.sentiment_normalized.value

    @property
    def category(self) -> str:
        return self.category_normalized.value

    @property
    def importance(self) -> str:
        return self.importance_normalized.value if self.importance_normalized else ""

    @property
    def risk_level(self) -> str:
        return self.risk_level_normalized.value

    def __repr__(self) -> str:
        return (
            "CommentAnalysisResult("
            f"is_improvement_needed={self.is_improvement_needed}, "
            f"is_abusive={self.is_abusive}, "
            f"sentiment={self.sentiment_normalized.value}, "
            f"category={self.category_normalized.value}, "
            f"importance={self.importance_normalized.value if self.importance_normalized else None}, "
            f"risk_level={self.risk_level_normalized.value}"
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
            llm_client,
            comment_text,
            course_name=course_name,
            question_text=question_text,
        )

    # --- 各種分析ロジックを呼び出し、最終的な判定を行う ---
    final_importance_score = scoring.determine_importance_score(llm_structured)
    is_improvement_needed = final_importance_score > 0.4

    # is_abusive: 安全性チェックモジュールで誹謗中傷を判定
    is_abusive = not safety.is_comment_safe(comment_text, llm_structured)
    
    # LLMの処理が走らなかった場合の処理を行っている。キーワード一致での予測を行っている。
    category_guess, sentiment_guess = aggregation.classify_comment(
        comment_text, llm_structured
    )

    sentiment_enum = _normalize_sentiment(llm_structured.sentiment or sentiment_guess)
    category_enum = _normalize_category(llm_structured.category or category_guess)
    importance_enum = _normalize_importance(llm_structured.importance_level)
    risk_level_enum = _normalize_risk_level(llm_structured.risk_level)

    # 最終的な結果を構築
    llm_structured.importance_score = final_importance_score
    llm_structured.risk_level = risk_level_enum.value
    llm_structured.category = category_enum.value
    llm_structured.importance_level = (
        importance_enum.value if importance_enum is not None else None
    )
    llm_structured.sentiment = sentiment_enum.value
    llm_structured.sentiment_normalized = sentiment_enum
    llm_structured.category_normalized = category_enum
    llm_structured.importance_normalized = importance_enum
    llm_structured.risk_level_normalized = risk_level_enum

    return CommentAnalysisResult(
        is_improvement_needed=is_improvement_needed,
        is_abusive=is_abusive,
        sentiment_normalized=sentiment_enum,
        category_normalized=category_enum,
        importance_normalized=importance_enum,
        risk_level_normalized=risk_level_enum,
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


SENTIMENT_ALIASES = {
    "positive": SentimentType.positive,
    "ポジティブ": SentimentType.positive,
    "negative": SentimentType.negative,
    "ネガティブ": SentimentType.negative,
    "neutral": SentimentType.neutral,
    "ニュートラル": SentimentType.neutral,
}

SENTIMENT_DISPLAY = {
    SentimentType.positive: "positive",
    SentimentType.negative: "negative",
    SentimentType.neutral: "neutral",
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


CATEGORY_ALIASES = {
    "講師": CategoryType.instructor,
    "運営": CategoryType.operation,
    "operations": CategoryType.operation,
    "operation": CategoryType.operation,
    "講義資料": CategoryType.material,
    "materials": CategoryType.material,
    "material": CategoryType.material,
    "講義内容": CategoryType.content,
}

CATEGORY_DISPLAY = {
    CategoryType.instructor: "講師",
    CategoryType.operation: "運営",
    CategoryType.material: "講義資料",
    CategoryType.content: "講義内容",
    CategoryType.other: "その他",
}


def _normalize_category(raw_value: str | None) -> CategoryType:
    """Map arbitrary category labels to the Enum we persist."""
    if not raw_value:
        return CategoryType.other

    normalized = raw_value.strip().lower()
    if normalized in CategoryType.__members__:
        return CategoryType[normalized]

    # Japanese labels and other aliases are matched without lower-casing
    if raw_value in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[raw_value]

    for key, mapped in CATEGORY_ALIASES.items():
        if key.lower() == normalized:
            return mapped

    return CategoryType.other


IMPORTANCE_ALIASES = {
    "high": ImportanceType.high,
    "medium": ImportanceType.medium,
    "low": ImportanceType.low,
    "高": ImportanceType.high,
    "中": ImportanceType.medium,
    "低": ImportanceType.low,
}

IMPORTANCE_DISPLAY = {
    ImportanceType.high: "high",
    ImportanceType.medium: "medium",
    ImportanceType.low: "low",
}


def _normalize_importance(raw_value: str | None) -> ImportanceType | None:
    """Map arbitrary importance labels to the Enum we persist."""
    if not raw_value:
        # 「その他」は Enum では表現せず、DB 上は NULL として扱う
        return None

    normalized = raw_value.strip().lower()
    if normalized in ImportanceType.__members__:
        return ImportanceType[normalized]

    if raw_value in IMPORTANCE_ALIASES:
        return IMPORTANCE_ALIASES[raw_value]

    for key, mapped in IMPORTANCE_ALIASES.items():
        if key.lower() == normalized:
            return mapped

    # 未知の値も NULL 扱い（DB では NULL、集計では low と同等に扱う）
    return None


RISK_LEVEL_ALIASES = {
    "flag": RiskLevelType.flag,
    "危険": RiskLevelType.flag,
    "safe": RiskLevelType.safe,
    "安全": RiskLevelType.safe,
    "other": RiskLevelType.other,
}

RISK_LEVEL_DISPLAY = {
    RiskLevelType.flag: "flag",
    RiskLevelType.safe: "safe",
    RiskLevelType.other: "other",
}


def _normalize_risk_level(raw_value: str | None) -> RiskLevelType:
    """Map arbitrary risk level labels to the Enum we persist."""
    if not raw_value:
        return RiskLevelType.other

    normalized = raw_value.strip().lower()
    if normalized in RiskLevelType.__members__:
        return RiskLevelType[normalized]

    if raw_value in RISK_LEVEL_ALIASES:
        return RISK_LEVEL_ALIASES[raw_value]

    for key, mapped in RISK_LEVEL_ALIASES.items():
        if key.lower() == normalized:
            return mapped

    return RiskLevelType.other
