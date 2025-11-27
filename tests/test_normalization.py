"""
正規化ロジックのテスト

LLMからのプレーンテキスト出力を正しくEnum型に変換できるかをテストします。
"""

import pytest

from app.analysis.analyzer import (
    _normalize_category,
    _normalize_importance,
    _normalize_risk_level,
    _normalize_sentiment,
)
from app.db.models import CategoryType, ImportanceType, RiskLevelType, SentimentType


class TestSentimentNormalization:
    """感情分析の正規化テスト"""

    def test_normalize_positive(self):
        """positive が正しく SentimentType.positive に変換される"""
        assert _normalize_sentiment("positive") == SentimentType.positive

    def test_normalize_negative(self):
        """negative が正しく SentimentType.negative に変換される"""
        assert _normalize_sentiment("negative") == SentimentType.negative

    def test_normalize_neutral(self):
        """neutral が正しく SentimentType.neutral に変換される"""
        assert _normalize_sentiment("neutral") == SentimentType.neutral

    def test_normalize_japanese_positive(self):
        """日本語ラベル「ポジティブ」が正しく変換される"""
        assert _normalize_sentiment("ポジティブ") == SentimentType.positive

    def test_normalize_japanese_negative(self):
        """日本語ラベル「ネガティブ」が正しく変換される"""
        assert _normalize_sentiment("ネガティブ") == SentimentType.negative

    def test_normalize_case_insensitive(self):
        """大文字小文字を区別せずに変換される"""
        assert _normalize_sentiment("POSITIVE") == SentimentType.positive
        assert _normalize_sentiment("Negative") == SentimentType.negative

    def test_normalize_empty_string(self):
        """空文字列は neutral にフォールバックする"""
        assert _normalize_sentiment("") == SentimentType.neutral
        assert _normalize_sentiment(None) == SentimentType.neutral

    def test_normalize_unknown_value(self):
        """未知の値は neutral にフォールバックする"""
        assert _normalize_sentiment("unknown") == SentimentType.neutral


class TestCategoryNormalization:
    """カテゴリの正規化テスト"""

    def test_normalize_operation(self):
        """「運営」が正しく CategoryType.operation に変換される"""
        assert _normalize_category("運営") == CategoryType.operation

    def test_normalize_instructor(self):
        """「講師」が正しく CategoryType.instructor に変換される"""
        assert _normalize_category("講師") == CategoryType.instructor

    def test_normalize_content(self):
        """「講義内容」が正しく CategoryType.content に変換される"""
        assert _normalize_category("講義内容") == CategoryType.content

    def test_normalize_material(self):
        """「講義資料」が正しく CategoryType.material に変換される"""
        assert _normalize_category("講義資料") == CategoryType.material

    def test_normalize_other(self):
        """「その他」が正しく CategoryType.other に変換される"""
        assert _normalize_category("その他") == CategoryType.other

    def test_normalize_empty_string(self):
        """空文字列は other にフォールバックする"""
        assert _normalize_category("") == CategoryType.other
        assert _normalize_category(None) == CategoryType.other

    def test_normalize_unknown_value(self):
        """未知の値は other にフォールバックする"""
        assert _normalize_category("unknown") == CategoryType.other


class TestImportanceNormalization:
    """重要度の正規化テスト"""

    def test_normalize_high(self):
        """high が正しく ImportanceType.high に変換される"""
        assert _normalize_importance("high") == ImportanceType.high

    def test_normalize_medium(self):
        """medium が正しく ImportanceType.medium に変換される"""
        assert _normalize_importance("medium") == ImportanceType.medium

    def test_normalize_low(self):
        """low が正しく ImportanceType.low に変換される"""
        assert _normalize_importance("low") == ImportanceType.low

    def test_normalize_case_insensitive(self):
        """大文字小文字を区別せずに変換される"""
        assert _normalize_importance("HIGH") == ImportanceType.high
        assert _normalize_importance("Medium") == ImportanceType.medium

    def test_normalize_empty_string(self):
        """空文字列は other にフォールバックする"""
        assert _normalize_importance("") == ImportanceType.other
        assert _normalize_importance(None) == ImportanceType.other

    def test_normalize_unknown_value(self):
        """未知の値は other にフォールバックする"""
        assert _normalize_importance("unknown") == ImportanceType.other


class TestRiskLevelNormalization:
    """リスクレベルの正規化テスト"""

    def test_normalize_flag(self):
        """Flag が正しく RiskLevelType.flag に変換される"""
        assert _normalize_risk_level("Flag") == RiskLevelType.flag

    def test_normalize_safe(self):
        """Safe が正しく RiskLevelType.safe に変換される"""
        assert _normalize_risk_level("Safe") == RiskLevelType.safe

    def test_normalize_case_insensitive(self):
        """大文字小文字を区別せずに変換される"""
        assert _normalize_risk_level("flag") == RiskLevelType.flag
        assert _normalize_risk_level("SAFE") == RiskLevelType.safe

    def test_normalize_empty_string(self):
        """空文字列は other にフォールバックする"""
        assert _normalize_risk_level("") == RiskLevelType.other
        assert _normalize_risk_level(None) == RiskLevelType.other

    def test_normalize_unknown_value(self):
        """未知の値は other にフォールバックする"""
        assert _normalize_risk_level("unknown") == RiskLevelType.other
