# app/analysis/safety.py

from typing import Any, Dict

# NGワードリスト (例)
# TODO: プロジェクトに合わせてNGワードを定義してください
NG_WORDS = ["不適切", "誹謗中傷", "差別"]

def is_comment_safe(comment_text: str, llm_output: Dict[str, Any]) -> bool:
    """
    LLMの出力やNGワードリストに基づき、コメントが安全かどうかを判定する

    Args:
        comment_text: コメント文字列
        llm_output: LLMからの分析結果

    Returns:
        安全な場合はTrue, 危険な場合はFalse
    """
    # --- ここからロジックを実装してください ---

    # 例1: NGワードが含まれていないかチェック
    if any(word in comment_text for word in NG_WORDS):
        return False

    # 例2: LLMが不適切と判定していないかチェック
    # llm_outputに 'is_safe' のようなキーで判定結果が格納されていると仮定
    if not llm_output.get("is_safe", True):
        return False

    # --- ここまで ---

    return True # 上記のチェックをすべてパスした場合
