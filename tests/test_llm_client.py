import httpx
import pytest

from app.analysis import analyzer
from app.services import (
    LLMClient,
    LLMClientConfig,
    LLMClientError,
    LLMResponseFormatError,
)


def test_llm_client_parses_openai_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": """{
                                "category": "要望",
                                "importance_level": "high",
                                "importance_score": 0.82,
                                "risk_level": "medium",
                                "sentiment": "ネガティブ",
                                "is_safe": true,
                                "summary": "要望のサマリ",
                                "tags": ["request"]
                            }"""
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        config=LLMClientConfig(
            provider="openai", base_url="https://example.com", model="dummy"
        ),
        transport=transport,
    )

    result = client.analyze_comment("講義が良かったが、改善も期待しています。")

    assert result.category == "要望"
    assert result.importance_level == "high"
    assert result.importance_score == pytest.approx(0.82)
    assert result.risk_level == "medium"
    assert result.is_safe is True
    assert result.summary == "要望のサマリ"


def test_llm_client_raises_on_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-valid-json"}}]},
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        config=LLMClientConfig(
            provider="openai", base_url="https://example.com", model="dummy"
        ),
        transport=transport,
    )

    with pytest.raises(LLMResponseFormatError):
        client.analyze_comment("テストコメント")


def test_analyze_comment_handles_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def analyze_comment(self, comment_text: str, **_: object):
            raise LLMClientError("simulated failure")

    analyzer.get_llm_client.cache_clear()
    monkeypatch.setattr(analyzer, "get_llm_client", lambda: FailingClient())

    result = analyzer.analyze_comment("改善してほしい点がありますが、概ね満足です。")

    assert result.category == "要望"
    assert result.sentiment in {"ニュートラル", "ポジティブ", "ネガティブ"}
    assert result.warnings
    assert any("failed" in warning for warning in result.warnings)
    assert result.summary
