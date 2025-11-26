from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.services import LLMAnalysisResult, LLMClient, LLMClientError

logger = logging.getLogger(__name__)


def analyze_with_llm(
    llm_client: LLMClient,
    comment_text: str,
    *,
    course_name: Optional[str] = None,
    question_text: Optional[str] = None,
) -> LLMAnalysisResult:
    """
    LLMを使用してコメントを多角的に分析し、結果を統合して返す。
    """
    # 各タスクが担当するキーを明示的に定義（full_analysisは使わず個別タスクのみ）
    core_tasks = {
        "sentiment": {"sentiment"},
        "importance": {"importance_level", "importance_score"},
        "categorization": {"category", "tags"},
        "risk_assessment": {"risk_level", "is_safe"},
    }
    all_known_keys = set.union(*core_tasks.values(), {"summary"})
    analysis_tasks = core_tasks

    merged_results: Dict[str, Any] = {}
    merged_warnings: List[str] = []
    merged_raw: Dict[str, Any] = {}

    def merge_task_result(task_name: str, result: LLMAnalysisResult) -> None:
        task_keys = analysis_tasks.get(task_name, all_known_keys)
        response_data = result.model_dump(exclude_unset=True)
        for key, value in response_data.items():
            if key in task_keys:
                merged_results[key] = value
            else:
                merged_warnings.append(
                    f"Task '{task_name}' returned unexpected key: '{key}'"
                )

        merged_warnings.extend(result.warnings)
        merged_raw[task_name] = result.raw

    def run_task(task_name: str) -> None:
        try:
            result = llm_client.analyze_comment(
                comment_text,
                analysis_type=task_name,
                course_name=course_name,
                question_text=question_text,
            )
        except (LLMClientError, ValueError) as exc:
            warning = f"LLM analysis for '{task_name}' failed: {exc}"
            logger.warning(warning)
            merged_warnings.append(warning)
            merged_raw[task_name] = {"error": str(exc)}
            return

        merge_task_result(task_name, result)

    def has_value(key: str) -> bool:
        """None以外の値が既に入っているかを確認する。"""
        return merged_results.get(key) is not None

    for task_name, task_keys in analysis_tasks.items():
        if not any(not has_value(key) for key in task_keys):
            continue
        run_task(task_name)

    merged_warnings = list(dict.fromkeys(merged_warnings))

    try:
        llm_structured = LLMAnalysisResult.model_validate(merged_results)
        llm_structured.warnings = merged_warnings
        llm_structured.raw = merged_raw
    except ValidationError as exc:
        llm_structured = LLMAnalysisResult(
            raw=merged_raw, warnings=[str(exc), *merged_warnings]
        )

    return llm_structured
