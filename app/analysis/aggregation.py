from __future__ import annotations

import re
from typing import Tuple

from app.services import LLMAnalysisResult

POSITIVE_KEYWORDS = (
    "良い",
    "良かった",
    "素晴らしい",
    "満足",
    "感謝",
    "助かった",
    "楽しい",
    "好き",
)
NEGATIVE_KEYWORDS = (
    "悪い",
    "不満",
    "困る",
    "難しい",
    "問題",
    "改善",
    "課題",
    "嫌",
    "最悪",
)

CATEGORY_KEYWORDS = {
    "要望": ("改善", "してほしい", "ほしい", "欲しい", "して欲しい", "希望"),
    "質問": ("どうして", "なぜ", "教えて", "わからない", "わかりません"),
    "不具合": ("バグ", "エラー", "落ちる", "動かない", "不具合"),
    "称賛": ("ありがとう", "感謝", "良かった", "最高"),
    "苦情": ("不満", "最悪", "腹立つ", "遅い"),
}


def classify_comment(
    comment_text: str, llm_output: LLMAnalysisResult
) -> Tuple[str, str]:
    """
    LLMの出力やキーワードを基にコメントを分類し、感情を判定する。
    """
    category = _determine_category(comment_text, llm_output)
    sentiment = _determine_sentiment(comment_text, llm_output)
    return category, sentiment


def _determine_category(comment_text: str, llm_output: LLMAnalysisResult) -> str:
    if llm_output.category:
        return llm_output.category

    lowered = comment_text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in comment_text for keyword in keywords):
            return category
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return "その他"


def _determine_sentiment(comment_text: str, llm_output: LLMAnalysisResult) -> str:
    if llm_output.sentiment:
        return llm_output.sentiment

    positive_score = _count_occurrences(comment_text, POSITIVE_KEYWORDS)
    negative_score = _count_occurrences(comment_text, NEGATIVE_KEYWORDS)

    if positive_score > negative_score:
        return "ポジティブ"
    if negative_score > positive_score:
        return "ネガティブ"
    return "ニュートラル"


def _count_occurrences(text: str, keywords: Tuple[str, ...]) -> int:
    return sum(len(re.findall(re.escape(keyword), text)) for keyword in keywords)
