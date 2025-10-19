# app/analysis/aggregation.py

from typing import Any, Dict, Tuple

def classify_comment(comment_text: str, llm_output: Dict[str, Any]) -> Tuple[str, str]:
    """
    LLMの出力やキーワードを基にコメントを分類し、感情を判定する

    Args:
        comment_text: コメント文字列
        llm_output: LLMからの分析結果

    Returns:
        (カテゴリ, 感情) のタプル (例: ("要望", "ポジティブ"))
    """
    # TODO: 分類・感情判定ロジックを実装
    category = "要望" # 仮のカテゴリ
    sentiment = "ポジティブ" # 仮の感情
    return category, sentiment
