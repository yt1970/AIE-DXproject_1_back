# app/analysis/analyzer.py

from . import scoring, aggregation, safety

class CommentAnalysisResult:
    """
    コメント分析結果を格納するデータクラス
    """
    def __init__(self, score: float, category: str, sentiment: str, is_safe: bool):
        self.score = score
        self.category = category
        self.sentiment = sentiment
        self.is_safe = is_safe

    def __repr__(self):
        return (f"CommentAnalysisResult(score={self.score}, category='{self.category}', "
                f"sentiment='{self.sentiment}', is_safe={self.is_safe})")


def analyze_comment(comment_text: str) -> CommentAnalysisResult:
    """
    単一のコメントを分析し、総合的な結果を返す

    Args:
        comment_text: 分析対象のコメント文字列

    Returns:
        分析結果をまとめたオブジェクト
    """
    # TODO: LLMへの問い合わせロジックをここに実装、または別のモジュールから呼び出す
    # llm_output = llm_client.ask(f"Analyze this comment: {comment_text}")
    llm_output = {} # 仮のLLM出力

    # 各分析ロジックを呼び出す
    importance_score = scoring.calculate_importance_score(comment_text, llm_output)
    category, sentiment = aggregation.classify_comment(comment_text, llm_output)
    is_safe = safety.is_comment_safe(comment_text, llm_output)

    return CommentAnalysisResult(
        score=importance_score,
        category=category,
        sentiment=sentiment,
        is_safe=is_safe
    )
