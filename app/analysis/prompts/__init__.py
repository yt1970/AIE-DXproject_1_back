from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict


@lru_cache
def load_prompts() -> Dict[str, str]:
    """
    promptsディレクトリからプロンプトファイルを読み込み、
    ファイル名をキーとする辞書を返す。
    """
    prompts: Dict[str, str] = {}
    prompt_dir = Path(__file__).parent

    for filename in os.listdir(prompt_dir):
        if filename.endswith(".txt"):
            task_name = filename.removesuffix(".txt")
            with open(prompt_dir / filename, "r", encoding="utf-8") as f:
                prompts[task_name] = f.read().strip()

    return prompts
