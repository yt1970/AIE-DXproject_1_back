# app/analysis/scoring.py

from typing import Any, List, Dict

def calculate_importance_score(comment_text: str, llm_output: Dict[str, Any]) -> float:
    """
    コメントの重要度スコアを計算する
    将来的には、具体性、緊急性などをLLMの出力から判定してスコアに反映する

    Args:
        comment_text: コメント文字列
        llm_output: LLMからの分析結果

    Returns:
        重要度スコア (例: 0.0 ~ 1.0)
    """
    # TODO: スコアリングロジックを実装
    # 例: コメントの長さや特定キーワードの有無、LLMの評価を基に計算
    score = 0.8 # 仮のスコア
    return score

def rank_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    スコアに基づいてコメントのリストをランキングする

    Args:
        comments: 'text'と'score'を含む辞書のリスト

    Returns:
        スコアの高い順にソートされたコメントのリスト
    """
    return sorted(comments, key=lambda c: c.get('score', 0), reverse=True)
