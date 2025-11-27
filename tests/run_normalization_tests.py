#!/usr/bin/env python3
"""
正規化ロジックのテストを実行するスクリプト
"""
import sys

sys.path.insert(0, "/app")

from app.analysis.analyzer import (
    _normalize_category,
    _normalize_importance,
    _normalize_risk_level,
    _normalize_sentiment,
)
from app.db.models import CategoryType, ImportanceType, RiskLevelType, SentimentType


def test_sentiment_normalization():
    """感情分析の正規化テスト"""
    print("Testing sentiment normalization...")

    # positive
    assert _normalize_sentiment("positive") == SentimentType.positive, "positive failed"
    assert (
        _normalize_sentiment("POSITIVE") == SentimentType.positive
    ), "POSITIVE (uppercase) failed"

    # negative
    assert _normalize_sentiment("negative") == SentimentType.negative, "negative failed"
    assert (
        _normalize_sentiment("Negative") == SentimentType.negative
    ), "Negative (mixed case) failed"

    # neutral
    assert _normalize_sentiment("neutral") == SentimentType.neutral, "neutral failed"

    # Japanese
    assert (
        _normalize_sentiment("ポジティブ") == SentimentType.positive
    ), "ポジティブ failed"
    assert (
        _normalize_sentiment("ネガティブ") == SentimentType.negative
    ), "ネガティブ failed"

    # Empty/None
    assert _normalize_sentiment("") == SentimentType.neutral, "empty string failed"
    assert _normalize_sentiment(None) == SentimentType.neutral, "None failed"

    # Unknown
    assert (
        _normalize_sentiment("unknown") == SentimentType.neutral
    ), "unknown value failed"

    print("✅ All sentiment normalization tests passed!")


def test_category_normalization():
    """カテゴリの正規化テスト"""
    print("Testing category normalization...")

    assert _normalize_category("運営") == CategoryType.operation, "運営 failed"
    assert _normalize_category("講師") == CategoryType.instructor, "講師 failed"
    assert _normalize_category("講義内容") == CategoryType.content, "講義内容 failed"
    assert _normalize_category("講義資料") == CategoryType.material, "講義資料 failed"
    assert _normalize_category("その他") == CategoryType.other, "その他 failed"

    # Empty/None
    assert _normalize_category("") == CategoryType.other, "empty string failed"
    assert _normalize_category(None) == CategoryType.other, "None failed"

    # Unknown
    assert _normalize_category("unknown") == CategoryType.other, "unknown value failed"

    print("✅ All category normalization tests passed!")


def test_importance_normalization():
    """重要度の正規化テスト"""
    print("Testing importance normalization...")

    assert _normalize_importance("high") == ImportanceType.high, "high failed"
    assert (
        _normalize_importance("HIGH") == ImportanceType.high
    ), "HIGH (uppercase) failed"
    assert _normalize_importance("medium") == ImportanceType.medium, "medium failed"
    assert (
        _normalize_importance("Medium") == ImportanceType.medium
    ), "Medium (mixed case) failed"
    assert _normalize_importance("low") == ImportanceType.low, "low failed"

    # Empty/None
    assert _normalize_importance("") == ImportanceType.other, "empty string failed"
    assert _normalize_importance(None) == ImportanceType.other, "None failed"

    # Unknown
    assert (
        _normalize_importance("unknown") == ImportanceType.other
    ), "unknown value failed"

    print("✅ All importance normalization tests passed!")


def test_risk_level_normalization():
    """リスクレベルの正規化テスト"""
    print("Testing risk level normalization...")

    assert _normalize_risk_level("Flag") == RiskLevelType.flag, "Flag failed"
    assert (
        _normalize_risk_level("flag") == RiskLevelType.flag
    ), "flag (lowercase) failed"
    assert _normalize_risk_level("Safe") == RiskLevelType.safe, "Safe failed"
    assert (
        _normalize_risk_level("SAFE") == RiskLevelType.safe
    ), "SAFE (uppercase) failed"

    # Empty/None
    assert _normalize_risk_level("") == RiskLevelType.other, "empty string failed"
    assert _normalize_risk_level(None) == RiskLevelType.other, "None failed"

    # Unknown
    assert (
        _normalize_risk_level("unknown") == RiskLevelType.other
    ), "unknown value failed"

    print("✅ All risk level normalization tests passed!")


if __name__ == "__main__":
    try:
        test_sentiment_normalization()
        test_category_normalization()
        test_importance_normalization()
        test_risk_level_normalization()

        print("\n" + "=" * 50)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 50)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
