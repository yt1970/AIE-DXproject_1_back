# AIE-DXproject Backend

このページはAIE-DXproject バックエンド解説です。

---

## 1. 何をするプロジェクト？
- 受講生アンケートなどの **CSV ファイル**をアップロードすると、任意回答欄だけを抽出して **LLM（大規模言語モデル）で分析**します。
- 分析結果は **データベースに保存**され、講義ごとに要約や重要度・リスクレベルを取得できます。
- FastAPI ベースの REST API として提供され、フロントエンドや業務ツールから呼び出せます。

---

## 2. はじめ方（ローカル開発）
1. Docker Desktop を起動し、リポジトリ直下で `docker compose up --build` を実行します。
2. ブラウザで `http://localhost:8000/docs` を開くと Swagger UI で API を触れます。
3. 解析したい CSV を `POST /api/v1/uploads` へ送ると、すぐ下のステータス API や結果取得 API で確認できます。

> **ポイント**: `.env` が無くても最初は SQLite + モック LLM で動きます。外部サービスとつなぐ場合は後述の設定を追加してください。

---

## 3. システム全体像

```
               ┌───────────────────┐
               │ CSV / メタデータ │
               └────────┬──────────┘
                        │ POST /api/v1/uploads
                        v
          ┌──────────────────────────────────────┐
          │ FastAPI (app/main.py)                │
          │ - 入力バリデーション                 │
          │ - 任意コメント列の検証              │
          │ - ファイル保存                      │
          │ - タスク投入 (Celery)               │
          └──────────────┬─────────────────┘
                         │ task_id
                         v
                ┌────────────────────┐
                │ メッセージブローカー │
                │ (Redis / SQS など)  │
                └────────┬──────────┘
                         │
                         v
          ┌──────────────────────────────────────┐
          │ Celery Worker (app/workers/tasks.py) │
          │ - CSV 取得 (Storage)                 │
          │ - LLM 分析                           │
          │ - DB 登録                            │
          │ - 進捗更新                           │
          └──────────────┬───────────────┬──────┘
                         │               │
              ┌──────────v───┐   ┌───────v────────┐
              │ Storage       │   │ LLM Client     │
              │ (Local / S3)  │   │ (OpenAI 等 or │
              │               │   │  モック)       │
              └──────────────┘   └───────────────┘
                         │               │
                         └────┬──────────┘
                              v
                 ┌──────────────────────────┐
                 │ Database (SQLAlchemy)    │
                 │ - uploaded_file テーブル │
                 │ - comment テーブル       │
                 └──────────┬──────────────┘
                            │
          ┌─────────────────v──────────────────┐
          │ API                                │
          │ - GET /uploads/{id}/status         │
          │ - GET /courses/{course}/comments   │
          └───────────────────────────────────┘
```

---

## 4. リクエストの流れ（CSV アップロード時）
1. **クライアント**が `metadata`（講義名・日付・回数など）付きで CSV を送信。
2. アップロード API がヘッダーをチェックし、`（任意）` で始まる列だけを抽出できるか検証。
3. CSV ファイルはストレージ（ローカル/S3）へ保存され、`uploaded_file` レコードが `QUEUED` 状態で作成されます。
4. Celery ワーカーがバックグラウンドでタスクを受け取り、コメント単位で LLM 分析を実行。
5. 成功したコメント件数・エラー内容・開始/完了時刻などを `uploaded_file` テーブルへ書き戻し、`comment` テーブルには分析結果を保存。

これにより、API は即座に応答しつつ、重い LLM 分析をバックエンドで処理できます。ステータス API からは `QUEUED` → `PROCESSING` → `COMPLETED` / `FAILED` の進捗が確認できます。

---

## 5. バックグラウンド処理のポイント

- Celery を採用し、ブローカー（Redis / Amazon SQS など）を仲介して FastAPI 本体と分析ワーカーを疎結合にしています。
- `.env` で `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER` などを切り替え可能。開発環境では eager（同期実行）にしてブローカー無しでも動かせます。
- `uploaded_file` テーブルには `task_id`, `processing_started_at`, `processing_completed_at`, `error_message` などの列を追加し、UI から処理状況をポーリング表示できます。
- ワーカー側では CSV のダウンロード、コメント抽出、LLM 呼び出し、結果保存を一貫して実施する `analyze_and_store_comments` パイプラインを利用します。
- ストレージクライアントは `save` / `load` の両方を実装しているため、ローカル保存でも S3 保存でも同じコードで動作します。

---

## 6. 主要モジュールと役割

| ディレクトリ / ファイル | 役割の概要 |
|-------------------------|------------|
| `app/main.py` | FastAPI アプリの初期化。起動時にマイグレーションを実行し、API を登録します。 |
| `app/api/upload.py` | CSV アップロードを受け付け、ストレージ保存と Celery タスク投入を担当。 |
| `app/api/analysis.py` | アップロード済みファイルの処理ステータスを返す API。 |
| `app/api/comments.py` | 講義別に分析済みコメントを返す API。ページングにも対応。 |
| `app/analysis/` | 重要度スコア計算、カテゴリ推定、安全性チェックなど分析ロジックを分割管理。 |
| `app/services/llm_client.py` | LLM API との通信層。OpenAI / Azure / 汎用 HTTP / モックの切り替えを吸収。 |
| `app/services/storage.py` | アップロードファイルをローカル or S3 に保存するクライアント。 |
| `app/services/upload_pipeline.py` | CSV 検証とコメント分析/保存のユーティリティ。API とワーカー双方から利用。 |
| `app/workers/` | Celery アプリ設定とタスク定義。`process_uploaded_file` が非同期分析を実行。 |
| `app/db/models.py` | SQLAlchemy モデル定義。`UploadedFile` と `Comment` のリレーションを構成。 |
| `app/core/settings.py` | Pydantic Settings を使った設定読み込み。`.env` や環境変数から取得。 |
| `infra/` | AWS CDK によるデプロイ構成（ECS Fargate、GitHub Actions 用 IAM など）。 |

---

## 7. データモデル（シンプルな ER 図）

```
┌──────────────────────────────┐
│ uploaded_file                │
│ ──────────────────────────── │
│ file_id (PK)                 │
│ course_name                  │
│ lecture_date                 │
│ lecture_number               │
│ status (QUEUED/PROCESSING/…) │
│ s3_key (保存先URI)           │
│ task_id                      │
│ total_rows / processed_rows  │
│ processing_started_at        │
│ processing_completed_at      │
│ error_message                │
└───────┬──────────────────────┘
        │ 1対多 (file_id)
        v
┌──────────────────────────────┐
│ comment                      │
│ ──────────────────────────── │
│ id (PK)                      │
│ file_id (FK)                 │
│ comment_text                 │
│ llm_category / sentiment     │
│ llm_summary                  │
│ llm_importance_level / score │
│ llm_risk_level               │
│ processed_at                 │
└──────────────────────────────┘
```

- `UploadedFile` は講義単位のアップロード履歴を表し、同じ講義・回の重複をユニーク制約で防ぎます。
- `Comment` は分析済みの一件コメントです。アップロードされた CSV のコメントセルと 1 対 1 で対応します。

---

## 8. 設定方法（`.env` で管理）
- `DATABASE_URL`: 例 `postgresql+psycopg://user:pass@host:5432/db`。未設定時は SQLite にフォールバック。
- `LLM_PROVIDER`: `mock`（既定） / `openai` / `azure_openai` / `generic` から選択。
- `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` など: プロバイダに応じて指定。
- `UPLOAD_BACKEND`: `local` or `s3`。S3 の場合は `UPLOAD_S3_BUCKET`, `AWS_*` 認証情報が必要。
- `CELERY_BROKER_URL`: `redis://` や `sqs://` など、タスクブローカーの接続先。
- `CELERY_RESULT_BACKEND`: 進捗を記録したい場合のバックエンド。不要なら空のままでも可。
- `CELERY_TASK_ALWAYS_EAGER`: `true` にするとワーカー無しで同期実行（開発・テスト向け）。
- 値はすべて `app/core/settings.py` の Pydantic Settings に集約され、FastAPI から利用されます。

---

## 9. 開発フローと品質担保
1. フィーチャーブランチを作成。
2. `black . && isort .` でフォーマット。
3. `pytest`（コンテナ内でも OK）でテスト実行。
4. Pull Request を作成し、GitHub Actions の CI パイプラインで確認。

CI では、ユニットテストに加えて CDK テンプレートの合成テストも実行されます。main ブランチへの push 時は Docker イメージをビルドし、Amazon ECR にプッシュします。

---

## 10. 本番運用へのヒント
- **LLM と S3 の本番設定**: `.env.example` をコピーし、必要なキーを入力して `.env` を用意してください。
- **データベースマイグレーション**: モデル変更時は `alembic revision --autogenerate -m "add column"` → `alembic upgrade head` を行います。
- **インフラ更新**: `infra/README.md` の手順に従い、CDK でスタックをデプロイします。GitHub Actions 用 OIDC ロールを設定すると CI から安全にデプロイ可能です。
- **監視**: `GET /health` で稼働確認を自動化できます。将来的にメトリクスを追加する余地もあります。

---

## 11. 用語ミニ辞典
- **LLM (Large Language Model)**: ChatGPT に代表される文章生成モデル。ここではコメント分類・要約・リスク判定に利用しています。
- **FastAPI**: Python 製の高速 Web API フレームワーク。自動ドキュメント生成や型ヒント連携が特徴。
- **Alembic**: SQLAlchemy のマイグレーション管理ツール。データベースのスキーマ変更をバージョン管理できます。
- **AWS CDK**: インフラをコードで記述するツールセット。TypeScript や Python でクラウド構成を管理できます。


