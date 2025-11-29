# 開発ガイド

AIE-DXプロジェクトの開発環境セットアップとワークフロー。

## 前提条件

- Python 3.11+
- Docker & Docker Compose（コンテナ環境を使用する場合）
- PostgreSQL または SQLite

## ローカル環境セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd AIE-DXproject_1_back
```

### 2. 仮想環境の作成

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# または
venv\Scripts\activate  # Windows
```

### 3. 依存パッケージのインストール

```bash
# 本番依存パッケージ
pip install -r requirements.txt

# 開発・テスト依存パッケージ
pip install -r requirements-dev.txt
```

### 4. 環境変数の設定

```bash
# .env.example をコピー
cp .env.example .env

# .env を編集
# 最低限必要な設定:
# - DATABASE_URL
# - LLM_API_KEY
```

`.env` ファイルの例:
```bash
ENV=development
DEBUG=True
TITLE="AIE-DX Backend API"

# Database
DATABASE_URL=sqlite:///./app_dev.sqlite3
# または PostgreSQL
# DATABASE_URL=postgresql://user:password@localhost:5432/aiedx

# LLM API
LLM_API_KEY=your-api-key-here
LLM_PROVIDER=openai  # or anthropic

# Storage
STORAGE_TYPE=local  # or s3
LOCAL_STORAGE_PATH=./var/uploads

# Redis (Celery用)
REDIS_URL=redis://localhost:6379/0
```

### 5. データベースマイグレーション

```bash
# マイグレーション適用
alembic upgrade head
```

### 6. 開発サーバー起動

```bash
# FastAPI開発サーバー
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

ブラウザで http://localhost:8000/docs にアクセスしてSwagger UIを確認できます。

---

## Docker を使った開発

### Docker Compose で全環境を起動

```bash
docker compose up --build
```

これにより以下が起動します：
- FastAPI アプリケーション (port 8000)
- PostgreSQL (port 5432)
- Redis (port 6379)
- Celery Worker

### 個別コンテナの操作

```bash
# ログ確認
docker compose logs -f app

# コンテナに入る
docker compose exec app bash

# マイグレーション実行
docker compose exec app alembic upgrade head

# テスト実行
docker compose exec app pytest
```

---

## テスト

### 全テスト実行

```bash
pytest
```

### カバレッジ付き実行

```bash
pytest --cov=app --cov-report=html
```

カバレッジレポートは `htmlcov/index.html` に生成されます。

### 特定のテストファイルのみ実行

```bash
pytest tests/test_api.py
pytest tests/test_services.py -v
```

### テストDBについて

テストは自動的にインメモリSQLiteデータベースを使用します。テスト実行前に自動的にマイグレーションが適用され、テスト後にクリーンアップされます。

---

## データベースマイグレーション

### マイグレーション生成

モデル（`app/db/models.py`）を変更した後：

```bash
# 自動でマイグレーションファイル生成
alembic revision --autogenerate -m "変更内容の説明"

# 例
alembic revision --autogenerate -m "Add user table"
```

### マイグレーション適用

```bash
# 最新まで適用
alembic upgrade head

# 1つ進める
alembic upgrade +1

# 特定バージョンまで適用
alembic upgrade <revision_id>
```

### ロールバック

```bash
# 1つ戻す
alembic downgrade -1

# 特定バージョンまで戻す
alembic downgrade <revision_id>

# 全て戻す
alembic downgrade base
```

### マイグレーション履歴確認

```bash
# 現在のバージョン
alembic current

# マイグレーション履歴
alembic history

# 詳細表示
alembic history --verbose
```

---

## コードフォーマット

### Black（コードフォーマッタ）

```bash
# フォーマット
black .

# チェックのみ
black --check .
```

### isort（インポート整理）

```bash
# インポート整理
isort .

# チェックのみ
isort --check-only .
```

---

## デバッグ

### VS Code デバッグ設定

`.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "app.main:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000"
      ],
      "jinja": true,
      "justMyCode": false
    }
  ]
}
```

### ログレベル設定

環境変数でログレベルを変更：
```bash
export LOG_LEVEL=DEBUG
uvicorn app.main:app --reload
```

### データベースクエリのログ

SQLAlchemyのクエリログを有効化：
```python
# app/db/session.py
engine = create_engine(
    DATABASE_URL,
    echo=True  # クエリログを出力
)
```

---

## Celery ワーカー

### ワーカー起動

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

### タスク確認

```bash
# タスク一覧
celery -A app.workers.celery_app inspect registered

# アクティブなタスク
celery -A app.workers.celery_app inspect active

# 予約済みタスク
celery -A app.workers.celery_app inspect reserved
```

---

## トラブルシューティング

### マイグレーションエラー

```bash
# マイグレーションをリセット（開発環境のみ）
alembic downgrade base
alembic upgrade head
```

### データベースリセット

```bash
# SQLiteの場合
rm app_dev.sqlite3
alembic upgrade head

# PostgreSQLの場合
dropdb aiedx
createdb aiedx
alembic upgrade head
```

### 依存パッケージの問題

```bash
# キャッシュクリアして再インストール
pip cache purge
pip install -r requirements.txt --force-reinstall
```

---

## 開発ワークフロー

1. **機能開発**
   - ブランチを作成: `git checkout -b feature/new-feature`
   - コードを編集
   - テストを追加・実行: `pytest`
   - フォーマット: `black . && isort .`

2. **マイグレーション**
   - モデル変更
   - マイグレーション生成: `alembic revision --autogenerate -m "..."`
   - マイグレーション確認・編集
   - 適用: `alembic upgrade head`

3. **コミット・プッシュ**
   - `git add .`
   - `git commit -m "説明"`
   - `git push origin feature/new-feature`

4. **プルリクエスト**
   - GitHub上でPR作成
   - CI/CDパイプラインの確認
   - レビュー・マージ

---

## 参考リソース

- [FastAPI ドキュメント](https://fastapi.tiangolo.com/)
- [SQLAlchemy ドキュメント](https://docs.sqlalchemy.org/)
- [Alembic チュートリアル](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Celery ドキュメント](https://docs.celeryproject.org/)
