from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.analysis.prompts import load_prompts
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# プロンプト定義

PROMPT_TEMPLATE_BASE = """
あなたは大学の講義改善を支援する優秀なアシスタントです。
これから渡される、ある講義に対する学生からのフィードバックコメントを分析してください。

## 講義名
{course_name}

## 質問事項項目名
{question_text}

## 質問事項に対する学生からのコメント
```
{comment_text}
```

## 指示
{instructions}
"""


# 例外定義
class LLMClientError(Exception):
    """LLMクライアント共通例外。"""


class LLMTimeoutError(LLMClientError):
    """LLM呼び出しのタイムアウト。"""


class LLMResponseFormatError(LLMClientError):
    """LLM応答形式が想定外のとき。"""


# Pydanticモデル定義
class LLMAnalysisResult(BaseModel):
    """LLM応答を正規化したモデル。"""

    category: Optional[str] = None
    priority: Optional[str] = Field(
        default=None, description="重要度 (high, medium, low)"
    )
    fix_difficulty: Optional[str] = Field(
        default=None, description="修正難易度 (easy, hard, none)"
    )
    risk_level: Optional[str] = Field(
        default=None, description="危険度ラベル (例: none, low, medium, high)"
    )
    sentiment: Optional[str] = None
    is_safe: Optional[bool] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class LLMClientConfig(BaseModel):
    """LLMクライアント設定。"""

    provider: Literal["mock", "generic", "openai", "azure_openai"] = "mock"
    base_url: Optional[str] = Field(
        default=None, description="LLM APIのエンドポイントURL"
    )
    model: Optional[str] = Field(default=None, description="使用するモデル名")
    api_key: Optional[str] = Field(default=None, description="APIキー")
    api_version: Optional[str] = Field(
        default=None, description="APIバージョン (Azure向け)"
    )
    organization: Optional[str] = Field(
        default=None, description="OpenAI組織IDなど、必要であれば設定"
    )
    timeout_seconds: float = Field(default=15.0, gt=0.0, description="タイムアウト秒数")
    request_template: Optional[str] = Field(
        default=None, description="プロンプトのテンプレート (OpenAIのsystem promptなど)"
    )
    extra_headers: Dict[str, str] = Field(
        default_factory=dict, description="リクエストに追加で付与するヘッダ"
    )
    enable_response_format: bool = Field(
        default=True,
        description="OpenAI系APIでresponse_formatをJSONオブジェクトに固定するかどうか",
    )

    def require_external_api(self) -> bool:
        """モック以外を利用する場合にTrueを返す。"""
        return self.provider != "mock"


# クライアント本体
@dataclass
class LLMClient:
    """LLM APIとの通信と整形を行う。"""

    config: LLMClientConfig
    transport: Optional[httpx.BaseTransport] = None

    def __post_init__(self) -> None:
        if self.config.require_external_api() and not self.config.base_url:
            raise ValueError(
                "LLMClientConfig.base_url is required when provider is not 'mock'."
            )

    def analyze_comment(
        self,
        comment_text: str,
        *,
        analysis_type: str = "full_analysis",
        course_name: Optional[str] = None,
        question_text: Optional[str] = None,
    ) -> LLMAnalysisResult:
        """コメントをLLMに投げ整形済み結果を返す。"""
        if not comment_text:
            raise ValueError("comment_text must not be empty")

        if self.config.provider == "mock":
            # モックは分析タイプを問わず固定値を返す
            logger.debug(
                "LLM provider is 'mock'. Returning mock response for task: %s",
                analysis_type,
            )
            mock_payload: Dict[str, Any] = {}
            if analysis_type == "sentiment":
                mock_payload = {"sentiment": "neutral"}
            elif analysis_type == "importance":
                mock_payload = {"importance_level": "low", "importance_score": 0.1}
            elif analysis_type == "categorization":
                mock_payload = {"category": "その他"}
            elif analysis_type == "risk_assessment":
                mock_payload = {"risk_level": "none", "is_safe": True}
            else:  # full_analysis or unknown
                mock_payload = {
                    "category": "その他",
                    "sentiment": "neutral",
                    "priority": "low",
                    "fix_difficulty": "easy",
                    "risk_level": "none",
                    "is_safe": True,
                    "summary": comment_text[:50],
                    "tags": [],
                }
            # 実応答にはraw/warningsが無いので呼び出し側で補完する
            return LLMAnalysisResult.model_validate(mock_payload)

        payload = self._build_payload(
            comment_text,
            analysis_type=analysis_type,
            course_name=course_name,
            question_text=question_text,
        )
        headers = self._build_headers()
        params = self._build_query_params()

        try:
            with httpx.Client(
                timeout=self.config.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.config.base_url, json=payload, headers=headers, params=params
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM API call timed out") from exc
        except httpx.HTTPStatusError as exc:
            # エラー応答の本文から、より詳細な情報を取得しようと試みる
            try:
                error_details = exc.response.json()
            except json.JSONDecodeError:
                error_details = exc.response.text
            raise LLMClientError(
                (
                    f"LLM API returned HTTP error: {exc.response.status_code} - "
                    f"{error_details}"
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"LLM API communication error: {exc!r}") from exc

        structured_payload = self._extract_structured_payload(response)
        normalized_payload = self._normalize_structured_payload(structured_payload)

        try:
            result = LLMAnalysisResult.model_validate(normalized_payload)
        except ValidationError as exc:
            warning = "Failed to validate LLM response against schema; falling back to raw payload."
            logger.warning("%s Payload=%s Error=%s", warning, structured_payload, exc)
            result = LLMAnalysisResult(
                raw=structured_payload,
                warnings=[warning, str(exc)],
            )

        # 正規化後にrawを再設定
        result.raw = structured_payload
        # 正規化で出た警告を重複なく統合
        normalized_warnings = normalized_payload.get("warnings", [])
        if normalized_warnings:
            result.warnings.extend(
                [w for w in normalized_warnings if w not in result.warnings]
            )

        return result

    # 内部ユーティリティ
    def _build_payload(
        self,
        comment_text: str,
        *,
        analysis_type: str,
        course_name: Optional[str],
        question_text: Optional[str],
    ) -> Dict[str, Any]:
        course_name_str = course_name or "（指定なし）"
        question_text_str = question_text or "（指定なし）"

        all_prompts = load_prompts()
        instructions = all_prompts.get(analysis_type) or all_prompts.get(
            "full_analysis", ""
        )

        final_prompt = (
            PROMPT_TEMPLATE_BASE.format(
                course_name=course_name_str,
                question_text=question_text_str,
                comment_text=comment_text,
                instructions=instructions,
            )
            .replace("\n", " ")
            .strip()
        )

        # 3. キャッシュキーの生成 (D. キャッシュキーの固定)
        # プロンプトの固定部分の内容（BASE_PROMPT_KEY + instructions + 質問事項名）に基づきハッシュキーを生成する
        BASE_PROMPT_KEY = "test"
        fixed_content_string = f"{BASE_PROMPT_KEY}|{instructions}"
        GLOBAL_FIXED_CACHE_KEY = hashlib.sha256(
            fixed_content_string.encode("utf-8")
        ).hexdigest()

        if self.config.provider in {"openai", "azure_openai"}:
            payload: Dict[str, Any] = {
                "model": self.config.model,
                "messages": [
                    {"role": "user", "content": final_prompt},
                ],
            }
            if self.config.enable_response_format:
                payload["response_format"] = {"type": "json_object"}
            return payload

        # generic向けの簡易リクエスト
        request_body: Dict[str, Any] = {
            "comment": comment_text,
            "instructions": final_prompt,
        }
        if self.config.model:
            request_body["model"] = self.config.model
        return request_body

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self.config.extra_headers)

        if self.config.api_key:
            if self.config.provider in {"openai", "azure_openai"}:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            else:
                headers.setdefault("X-API-Key", self.config.api_key)

        if self.config.organization and self.config.provider == "openai":
            headers["OpenAI-Organization"] = self.config.organization

        return headers

    def _build_query_params(self) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if self.config.provider == "azure_openai" and self.config.api_version:
            params["api-version"] = self.config.api_version
        return params

    def _extract_structured_payload(self, response: httpx.Response) -> Dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            text = response.text.strip()
            raise LLMResponseFormatError(
                f"LLM API returned non-JSON response: {text[:200]}"
            ) from exc

        return self._unwrap_response_body(body)

    def _unwrap_response_body(self, body: Any) -> Dict[str, Any]:
        """プロバイダごとの応答を辞書に正規化する。"""
        if isinstance(body, dict):
            candidate_keys = ("analysis", "result", "data")
            for key in candidate_keys:
                value = body.get(key)
                if isinstance(value, dict):
                    return value

            if "choices" in body and isinstance(body["choices"], list):
                return self._extract_from_choices(body["choices"])

            return self._ensure_dict(body)

        if isinstance(body, list) and body:
            return self._unwrap_response_body(body[0])

        raise LLMResponseFormatError(
            f"Unexpected LLM response structure: {type(body).__name__}"
        )

    def _extract_from_choices(self, choices: List[Any]) -> Dict[str, Any]:
        if not choices:
            raise LLMResponseFormatError("LLM response choices array was empty.")

        first_choice = choices[0] or {}
        message = first_choice.get("message") or {}
        content = message.get("content")

        if content is None and isinstance(first_choice.get("content"), list):
            # OpenAI responses with content as a list of parts
            content_parts = first_choice["content"]
            content = (
                "".join(
                    part.get("text", "")
                    for part in content_parts
                    if isinstance(part, dict)
                ).strip()
                or None
            )

        if content is None and isinstance(first_choice.get("content"), str):
            content = first_choice["content"]

        if content is None:
            raise LLMResponseFormatError("LLM response missing message content.")

        if isinstance(content, str):
            cleaned = self._strip_code_fences(content.strip())
            try:
                return self._ensure_dict(json.loads(cleaned))
            except json.JSONDecodeError as exc:
                raise LLMResponseFormatError(
                    "Failed to parse JSON content from LLM choice."
                ) from exc

        if isinstance(content, list):
            concatenated = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            ).strip()
            cleaned = self._strip_code_fences(concatenated)
            try:
                return self._ensure_dict(json.loads(cleaned))
            except json.JSONDecodeError as exc:
                raise LLMResponseFormatError(
                    "Failed to parse JSON content from structured LLM messages."
                ) from exc

        if isinstance(content, dict):
            return self._ensure_dict(content)

        raise LLMResponseFormatError(
            f"Unsupported message content type: {type(content).__name__}"
        )

    def _strip_code_fences(self, text: str) -> str:
        if text.startswith("```"):
            # 先頭の```langを除去
            parts = text.split("\n", 1)
            text = parts[1] if len(parts) > 1 else ""
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        return text.strip()

    def _ensure_dict(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        raise LLMResponseFormatError(
            f"LLM response is not a JSON object: {type(payload).__name__}"
        )

    def _normalize_structured_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(payload)
        warnings: List[str] = []

        # 代表的なキー差異を吸収
        key_aliases = {
            "importance": "priority",
            "importanceLevel": "priority",
            "importance_label": "priority",
            "priority": "priority",
            "fix_difficulty": "fix_difficulty",
            "fixDifficulty": "fix_difficulty",
            "danger_level": "risk_level",
            "danger": "risk_level",
            "risk_assessment": "risk_level",
            "risk": "risk_level",
            "safety": "is_safe",
            "safe": "is_safe",
        }

        for alias, target in key_aliases.items():
            if alias in normalized and target not in normalized:
                normalized[target] = normalized[alias]

        # 真偽値をboolに統一
        if "is_safe" in normalized and not isinstance(normalized["is_safe"], bool):
            value = normalized["is_safe"]
            if isinstance(value, str):
                normalized["is_safe"] = value.lower() in {"true", "1", "yes", "safe"}
            else:
                normalized["is_safe"] = bool(value)

        if "tags" in normalized and not isinstance(normalized["tags"], list):
            tags_value = normalized["tags"]
            if isinstance(tags_value, str):
                normalized["tags"] = [
                    tag.strip() for tag in tags_value.split(",") if tag.strip()
                ]
            else:
                warnings.append("tags field was not a list; dropping its value.")
                normalized["tags"] = []

        normalized["raw"] = payload
        if warnings:
            normalized["warnings"] = warnings

        return normalized


# 設定読み込みヘルパー
@lru_cache
def build_default_llm_config() -> LLMClientConfig:
    """環境変数からLLMクライアントの設定を構築する。"""
    settings = get_settings()
    provider = settings.llm.provider
    mapped_provider: Literal["mock", "generic", "openai", "azure_openai"]
    if provider in {"mock", "disabled"}:
        mapped_provider = "mock"
    elif provider in {"openai", "gpt"}:
        mapped_provider = "openai"
    elif provider in {"azure", "azure_openai"}:
        mapped_provider = "azure_openai"
    else:
        mapped_provider = "generic"

    config = LLMClientConfig(
        provider=mapped_provider,
        base_url=settings.llm.api_base,
        model=settings.llm.model,
        api_key=settings.llm.api_key,
        api_version=settings.llm.api_version,
        organization=settings.llm.organization,
        timeout_seconds=settings.llm.timeout_seconds,
        request_template=settings.llm.request_template,
        extra_headers=settings.llm.extra_headers,
    )

    return config
