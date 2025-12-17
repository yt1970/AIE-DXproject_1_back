from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from app.db.models import (
    CategoryType,
    FixDifficultyType,
    PriorityType,
    RiskLevelType,
    SentimentType,
)
from app.services import LLMClient, LLMClientConfig, build_default_llm_config

from . import aggregation, llm_analyzer, safety

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
        priority_normalized: PriorityType | None,
        fix_difficulty_normalized: FixDifficultyType | None,
    ) -> None:
        # DBのCommentAnalysisモデルと対応する属性
        self.is_improvement_needed = is_improvement_needed
        self.is_abusive = is_abusive
        self.sentiment_normalized = sentiment_normalized
        # LLM分析結果の詳細情報
        self.category_normalized = category_normalized
        self.summary = llm_result.summary
        self.priority_normalized = priority_normalized
        self.fix_difficulty_normalized = fix_difficulty_normalized
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
    def priority(self) -> str:
        return self.priority_normalized.value if self.priority_normalized else ""

    @property
    def fix_difficulty(self) -> str:
        return (
            self.fix_difficulty_normalized.value
            if self.fix_difficulty_normalized
            else ""
        )

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
            f"priority={self.priority_normalized.value if self.priority_normalized else None}, "
            f"fix_difficulty={self.fix_difficulty_normalized.value if self.fix_difficulty_normalized else None}, "
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
    # --- 各種分析ロジックを呼び出し、最終的な判定を行う ---
    # is_improvement_needed: PriorityがHighまたはMediumの場合にTrueとする

    priority_enum = _normalize_priority(llm_structured.priority)
    fix_difficulty_enum = _normalize_fix_difficulty(llm_structured.fix_difficulty)

    is_improvement_needed = False
    if priority_enum in (PriorityType.high, PriorityType.medium):
        is_improvement_needed = True

    # is_abusive: 安全性チェックモジュールで誹謗中傷を判定
    is_abusive = not safety.is_comment_safe(comment_text, llm_structured)

    # LLMの処理が走らなかった場合の処理を行っている。キーワード一致での予測を行っている。
    category_guess, sentiment_guess = aggregation.classify_comment(
        comment_text, llm_structured
    )

    sentiment_enum = _normalize_sentiment(llm_structured.sentiment or sentiment_guess)
    category_enum = _normalize_category(llm_structured.category or category_guess)

    # 既存コードで既に正規化しているが、念のため再取得（あるいは変数を再利用）
    # priority_enum, fix_difficulty_enum は上で定義済み
    risk_level_enum = _normalize_risk_level(llm_structured.risk_level)

    # 最終的な結果を構築
    llm_structured.risk_level = risk_level_enum.value
    llm_structured.category = category_enum.value
    llm_structured.priority = priority_enum.value if priority_enum is not None else None
    llm_structured.fix_difficulty = (
        fix_difficulty_enum.value if fix_difficulty_enum is not None else None
    )
    llm_structured.sentiment = sentiment_enum.value
    llm_structured.sentiment_normalized = sentiment_enum
    llm_structured.category_normalized = category_enum
    # llm_structured への割り当て（Pydanticモデル側には _normalized フィールドはないかもしれないが、
    # 既存コードで代入しているので踏襲するか、Pydantic側定義にはないなら不要）
    # ここではローカル変数として渡す

    return CommentAnalysisResult(
        is_improvement_needed=is_improvement_needed,
        is_abusive=is_abusive,
        sentiment_normalized=sentiment_enum,
        category_normalized=category_enum,
        priority_normalized=priority_enum,
        fix_difficulty_normalized=fix_difficulty_enum,
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


PRIORITY_ALIASES = {
    "high": PriorityType.high,
    "medium": PriorityType.medium,
    "low": PriorityType.low,
    "高": PriorityType.high,
    "中": PriorityType.medium,
    "低": PriorityType.low,
}


def _normalize_priority(raw_value: str | None) -> PriorityType | None:
    """Map arbitrary priority labels to the Enum we persist."""
    if not raw_value:
        return None

    normalized = raw_value.strip().lower()
    if normalized in PriorityType.__members__:
        return PriorityType[normalized]

    if raw_value in PRIORITY_ALIASES:
        return PRIORITY_ALIASES[raw_value]

    for key, mapped in PRIORITY_ALIASES.items():
        if key.lower() == normalized:
            return mapped

    return None


FIX_DIFFICULTY_ALIASES = {
    "easy": FixDifficultyType.easy,
    "hard": FixDifficultyType.hard,
    "none": FixDifficultyType.none,
    "簡単": FixDifficultyType.easy,
    "難しい": FixDifficultyType.hard,
    "なし": FixDifficultyType.none,
}


def _normalize_fix_difficulty(raw_value: str | None) -> FixDifficultyType | None:
    """Map arbitrary fix_difficulty labels to the Enum we persist."""
    if not raw_value:
        return None

    normalized = raw_value.strip().lower()
    if normalized in FixDifficultyType.__members__:
        return FixDifficultyType[normalized]

    if raw_value in FIX_DIFFICULTY_ALIASES:
        return FIX_DIFFICULTY_ALIASES[raw_value]

    for key, mapped in FIX_DIFFICULTY_ALIASES.items():
        if key.lower() == normalized:
            return mapped

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
