# Ruffの使用方法

Rust製の高速なPythonリンター・フォーマッターである **Ruff** の使い方について説明します。

## リント

```bash
# コードの問題を検出
uv run ruff check .

# 自動修正
uv run ruff check --fix .
```

## フォーマット

```bash
# 整形せずに確認のみ
uv run ruff format --check .

# コードを整形
uv run ruff format .
```
