from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache
def load_prompts() -> dict[str, str]:
    """
    promptsディレクトリからプロンプトファイルを読み込み、
    ファイル名をキーとする辞書を返す。
    """
    prompts: dict[str, str] = {}
    prompt_dir = Path(__file__).parent

    for filename in os.listdir(prompt_dir):
        if filename.endswith(".txt"):
            task_name = filename.removesuffix(".txt")
            with open(prompt_dir / filename, encoding="utf-8") as f:
                prompts[task_name] = f.read().strip()

    return prompts
