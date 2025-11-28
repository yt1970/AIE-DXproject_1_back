# AIE-DXプロジェクト１【バックエンド】

FastAPIで構築された授業アンケート分析システムのバックエンドサービス。CSVアップロード、LLMによるコメント分析、集計・可視化機能を提供します。

## クイックスタート

```bash
# Docker Composeで全環境を起動
docker compose up --build

# ブラウザでSwagger UIにアクセス
open http://localhost:8000/docs
```

## 機能概要

- **CSVアップロード**: 授業アンケートCSVを受け取り、データベースに正規化
- **LLM分析**: 自由記述コメントを感情分析、カテゴリ分類、重要度評価
- **集計処理**: NPS、平均スコア、スコア分布、コメント分類の自動集計
- **RESTful API**: フロントエンドへのデータ提供

## 技術スタック

- **FastAPI** - Webフレームワーク
- **SQLAlchemy** - ORM (7テーブルのリレーショナルモデル)
- **Alembic** - データベースマイグレーション管理
- **Celery + Redis** - 非同期バックグラウンドタスク処理
- **LLM API** - コメント分析 (OpenAI/Anthropic等)
- **Storage** - ローカル/S3対応の抽象化ストレージレイヤー

## プロジェクト構造

```
.
├── app/                          # FastAPIアプリケーション
│   ├── main.py                   # アプリケーションファクトリ
│   ├── api/                      # APIエンドポイント (7モジュール)
│   ├── core/                     # 設定管理
│   ├── db/                       # データベースモデル・セッション
│   ├── schemas/                  # Pydanticスキーマ
│   ├── services/                 # ビジネスロジック
│   ├── workers/                  # Celeryワーカー
│   └── analysis/                 # LLM分析パイプライン
├── tests/                        # ユニット・統合テスト
├── alembic/                      # データベースマイグレーション
├── infra/                        # AWS CDK インフラコード
├── docs/                         # ドキュメント
│   ├── database.md               # データベーススキーマ詳細
│   ├── api.md                    # APIエンドポイント詳細
│   ├── dataflow.md               # データフロー詳細
│   └── development.md            # 開発ガイド
├── Dockerfile                    # コンテナイメージ定義
├── docker-compose.yml            # ローカル開発環境
└── requirements.txt              # 依存パッケージ
```

## ドキュメント

詳細なドキュメントは `docs/` ディレクトリを参照してください：

- **[データベーススキーマ](docs/database.md)** - 7テーブルの詳細定義、ER図、命名規則
- **[API エンドポイント](docs/api.md)** - 全エンドポイントのリクエスト/レスポンス仕様
- **[データフロー](docs/dataflow.md)** - システムアーキテクチャと処理フロー詳細
- **[開発ガイド](docs/development.md)** - ローカル環境セットアップ、テスト、マイグレーション

## API概要

主要なAPIエンドポイント：

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| POST | `/api/v1/uploads` | CSVファイルアップロード |
| GET | `/api/v1/lectures` | 講義一覧取得 |
| GET | `/api/v1/comments` | コメント一覧取得 |
| GET | `/api/v1/metrics` | メトリクス集計データ取得 |
| GET | `/api/v1/dashboard` | ダッシュボードデータ取得 |

詳細は [docs/api.md](docs/api.md) および Swagger UI (`http://localhost:8000/docs`) を参照してください。

## データベース

7つのテーブルで構成されたリレーショナルデータベース：

1. **lectures** - 講義マスタ
2. **survey_batches** - アンケートバッチ
3. **survey_responses** - 個別回答（12種類のスコア）
4. **response_comments** - コメント + LLM分析結果
5. **survey_summaries** - 集計サマリー（NPS、平均スコア）
6. **score_distributions** - スコア分布
7. **comment_summaries** - コメント分類集計

詳細は [docs/database.md](docs/database.md) を参照してください。

## 開発

### ローカル環境セットアップ

```bash
# 依存パッケージインストール
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 環境変数設定
cp .env.example .env
# .envを編集してLLM APIキーなどを設定

# マイグレーション実行
alembic upgrade head

# 開発サーバー起動
uvicorn app.main:app --reload
```

### テスト

```bash
# 全テスト実行
pytest

# カバレッジ付き
pytest --cov=app --cov-report=html
```

詳細な開発手順は [docs/development.md](docs/development.md) を参照してください。

## デプロイ

AWS CDKを使ったデプロイ手順は [infra/README.md](infra/README.md) を参照してください。

## ライセンス

（ライセンス情報を追加してください）

