from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

# デフォルトのシステムプロンプト (OpenAI系API向け)
DEFAULT_SYSTEM_PROMPT = (
    "You analyze student feedback comments. "
    "Return a strict JSON object with the following keys: "
    "'category' (string), "
    "'importance_level' (string such as 'low', 'medium', or 'high'), "
    "'importance_score' (number between 0 and 1), "
    "'risk_level' (string such as 'none', 'low', 'medium', 'high', 'critical'), "
    "'sentiment' (string), "
    "'is_safe' (boolean), "
    "'summary' (string), "
    "'tags' (array of strings). "
    "Always respond with valid JSON. Do not include markdown."
)


# ---------------------------------------------------------------------------
# 例外定義
# ---------------------------------------------------------------------------
class LLMClientError(Exception):
    """ベースとなるLLMクライアント例外。"""


class LLMTimeoutError(LLMClientError):
    """LLM呼び出しのタイムアウトを表す例外。"""


class LLMResponseFormatError(LLMClientError):
    """LLM応答の形式が想定外だった場合に送出。"""


# ---------------------------------------------------------------------------
# Pydanticモデル定義
# ---------------------------------------------------------------------------
class LLMAnalysisResult(BaseModel):
    """LLMから取得した分析情報を正規化したデータモデル。"""

    category: Optional[str] = None
    importance_level: Optional[str] = Field(
        default=None, description="重要度ラベル (例: low, medium, high)"
    )
    importance_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="0~1の重要度スコア。スコアが提供されない場合はNone。",
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
    """LLMクライアントの設定値。"""

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


# ---------------------------------------------------------------------------
# クライアント本体
# ---------------------------------------------------------------------------
@dataclass
class LLMClient:
    """LLM APIとの通信とレスポンス整形を担当するクライアント。"""

    config: LLMClientConfig
    transport: Optional[httpx.BaseTransport] = None

    def __post_init__(self) -> None:
        if self.config.require_external_api() and not self.config.base_url:
            raise ValueError(
                "LLMClientConfig.base_url is required when provider is not 'mock'."
            )

    def analyze_comment(self, comment_text: str) -> LLMAnalysisResult:
        """コメントをLLMに送信し、整形済みの分析結果を返す。"""
        if not comment_text:
            raise ValueError("comment_text must not be empty")

        if self.config.provider == "mock":
            logger.debug("LLM provider set to 'mock'; returning fallback result.")
            return LLMAnalysisResult(
                category="その他",
                importance_level="low",
                importance_score=0.0,
                risk_level="none",
                sentiment="neutral",
                is_safe=True,
                summary=None,
                raw={"provider": "mock", "comment": comment_text},
                warnings=["LLM provider is 'mock'; returning default analysis."],
            )

        payload = self._build_payload(comment_text)
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
            raise LLMClientError(
                f"LLM API returned HTTP error: {exc.response.status_code}"
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

        # 正規化済みのrawデータを格納（Validationで上書きされる場合があるため再設定）
        result.raw = structured_payload
        # Validationが成功した場合でも正規化時の警告があれば付与
        normalized_warnings = normalized_payload.get("warnings", [])
        if normalized_warnings:
            result.warnings.extend(
                [w for w in normalized_warnings if w not in result.warnings]
            )

        return result

    # ------------------------------------------------------------------
    # 内部ユーティリティ
    # ------------------------------------------------------------------
    def _build_payload(self, comment_text: str) -> Dict[str, Any]:
        if self.config.provider in {"openai", "azure_openai"}:
            system_prompt = self.config.request_template or DEFAULT_SYSTEM_PROMPT
            payload: Dict[str, Any] = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": comment_text},
                ],
            }
            if self.config.enable_response_format:
                payload["response_format"] = {"type": "json_object"}
            return payload

        # genericプロバイダ向けのシンプルなリクエスト
        request_body: Dict[str, Any] = {
            "comment": comment_text,
            "instructions": self.config.request_template or DEFAULT_SYSTEM_PROMPT,
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
        """
        各種プロバイダのレスポンス形式を吸収して、最終的に辞書を返す。
        """
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
            # 先頭の ```lang を除去
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

        # キーのバリエーションを吸収
        key_aliases = {
            "importance": "importance_level",
            "importanceLevel": "importance_level",
            "importance_label": "importance_level",
            "priority": "importance_level",
            "danger_level": "risk_level",
            "danger": "risk_level",
            "risk": "risk_level",
            "safety": "is_safe",
            "safe": "is_safe",
        }

        for alias, target in key_aliases.items():
            if alias in normalized and target not in normalized:
                normalized[target] = normalized[alias]

        # スコアが文字列で返ってきた場合の対応
        score_keys = ("importance_score", "importanceScore")
        for key in score_keys:
            if key in normalized:
                try:
                    normalized["importance_score"] = (
                        float(normalized[key])
                        if normalized[key] is not None
                        else normalized.get("importance_score")
                    )
                except (TypeError, ValueError):
                    warnings.append(
                        f"importance_score could not be converted to float: {normalized[key]!r}"
                    )
                break

        # 真偽値の正規化
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


# ---------------------------------------------------------------------------
# 設定読み込みヘルパー
# ---------------------------------------------------------------------------
@lru_cache
def build_default_llm_config() -> LLMClientConfig:
    """環境変数からLLMクライアントの設定を構築する。"""
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    mapped_provider: Literal["mock", "generic", "openai", "azure_openai"]
    if provider in {"mock", "disabled"}:
        mapped_provider = "mock"
    elif provider in {"openai", "gpt"}:
        mapped_provider = "openai"
    elif provider in {"azure", "azure_openai"}:
        mapped_provider = "azure_openai"
    else:
        mapped_provider = "generic"

    timeout_env = os.getenv("LLM_TIMEOUT_SECONDS")
    try:
        timeout_seconds = float(timeout_env) if timeout_env else 15.0
    except ValueError:
        logger.warning(
            "Invalid LLM_TIMEOUT_SECONDS value '%s'; using default.", timeout_env
        )
        timeout_seconds = 15.0

    config = LLMClientConfig(
        provider=mapped_provider,
        base_url=os.getenv("LLM_API_BASE"),
        model=os.getenv("LLM_MODEL"),
        api_key=os.getenv("LLM_API_KEY"),
        api_version=os.getenv("LLM_API_VERSION"),
        organization=os.getenv("LLM_ORGANIZATION"),
        timeout_seconds=timeout_seconds,
        request_template=os.getenv("LLM_REQUEST_TEMPLATE"),
    )

    # 追加ヘッダのロード (JSON文字列を想定)
    extra_headers_raw = os.getenv("LLM_EXTRA_HEADERS")
    if extra_headers_raw:
        try:
            headers = json.loads(extra_headers_raw)
            if isinstance(headers, dict):
                config.extra_headers.update(headers)
            else:
                logger.warning("LLM_EXTRA_HEADERS must be a JSON object.")
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM_EXTRA_HEADERS as JSON.")

    return config
