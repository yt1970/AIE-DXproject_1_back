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
# 4分類への正規化用キーワード
FOUR_CATEGORY_KEYWORDS = {
    "講義資料": ("資料", "スライド", "配布", "教材", "pdf", "テキスト"),
    "運営": ("運営", "アナウンス", "連絡", "zoom", "録画", "出欠", "スケジュール", "配信", "会場", "受付"),
    "講義内容": ("内容", "説明", "構成", "進度", "難易度", "ペース", "事例", "演習", "課題"),
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


def _normalize_to_four_categories(source: str) -> str | None:
    if not source:
        return None
    lowered = source.lower()
    for cat, keywords in FOUR_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in source or kw.lower() in lowered:
                return cat
    # 単語マッチがなければNone（後段で判定）
    return None


def _determine_category(comment_text: str, llm_output: LLMAnalysisResult) -> str:
    # まずLLMのカテゴリを4分類に正規化する試み
    normalized = _normalize_to_four_categories(llm_output.category or "")
    if normalized:
        return normalized

    # LLMカテゴリが空/不明なら、本文から推定
    normalized_from_text = _normalize_to_four_categories(comment_text)
    if normalized_from_text:
        return normalized_from_text

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
