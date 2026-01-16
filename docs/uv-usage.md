# uvの使用方法

Rust製の高速なPythonパッケージマネージャーである **uv** の基本的な使い方と運用フローについて説明します。

## 1. インストール

OSに合わせて以下のコマンドを実行してください。

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. プロジェクトの初期化

新規プロジェクト、または既存プロジェクトのディレクトリで実行します。

```bash
# プロジェクトの初期化（pyproject.tomlの作成）
uv init

# 使用するPythonバージョンを固定（.python-versionの作成）
# 指定したバージョンが未インストールなら、自動でダウンロードされます
uv python pin 3.13
```

## 3. パッケージの管理

```bash
# パッケージの追加
uv add requests

# 開発用（テストツール・フォーマッタなど）として追加
uv add --dev pytest ruff

# パッケージの削除
uv remove requests

# 開発用パッケージの削除
uv remove --group dev pytest
```

## 4. プログラムの実行と同期

`uv` は仮想環境（`.venv`）を自動的に管理します。開発者が手動で `source .venv/bin/activate` する必要はありません。

```bash
# 仮想環境内での実行（依存関係のチェックも自動で行われます）
uv run uvicorn app.main:app --reload

# 明示的に pyproject.toml の内容を仮想環境（.venv）に反映させる場合
uv sync
```

## 5. アップデート

パッケージや `uv` 自体を最新の状態に保つためのコマンドです。

```bash
# 全パッケージを最新に更新し uv.lock を書き換える
uv lock --upgrade

# 特定のパッケージのみ最新にする
uv add requests@latest

# uv 自体のアップデート
uv self update
```

## 6. requirements.txt への書き出し (Export)

CI/CD環境や、uvを導入していない環境（サーバー等）向けにファイルを出力する場合に使用します。

| 出力内容 | コマンド |
| --- | --- |
| **本番用のみ** | `uv export --no-dev -o requirements.txt` |
| **開発用含む** | `uv export -o requirements-dev.txt` |

※ハッシュなしにしたい場合は `--no-hashes` オプションをつけてください。
