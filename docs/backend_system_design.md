バックエンドシステム設計書（AIE-DXproject Backend）
================================

概要
----
本ドキュメントは、AIE-DXproject のバックエンドに関する全体設計、コンポーネント構成、主要データモデル、主要フロー、運用・設定の要点をまとめたものです。CSV アップロードから LLM 分析、結果の蓄積および参照までの一連の処理を対象とします。

全体アーキテクチャ
------------------------------
- Web API 層: FastAPI アプリケーション（`app/main.py`）
  - ルーター: `app/api/`（uploads, analysis, comments, courses, lectures, metrics）
- アプリケーションサービス層:
  - アップロード/解析パイプライン: `app/services/upload_pipeline.py`
  - ストレージ抽象化（Local/S3）: `app/services/storage.py`
  - LLM クライアント: `app/services/llm_client.py`
  - 分析ロジック（集約/安全性/スコア）: `app/analysis/`
- バックグラウンド処理: Celery ワーカー（`app/workers/`）
- データアクセス層: SQLAlchemy モデル/セッション（`app/db/models.py`, `app/db/session.py`）
- マイグレーション: Alembic（`alembic/`）
- 設定: Pydantic Settings（`app/core/settings.py`）
- 実行基盤:
  - ローカル: Docker / docker-compose（`Dockerfile`, `docker-compose.yml`）
  - クラウド（任意）: AWS CDK による ECS on Fargate 参考スタック（`infra/`）

ランタイム構成
--------------
- FastAPI（Uvicorn）で HTTP API を提供
  - エントリポイント: `app/main.py`（`create_app()`, `/health` など）
  - ルーター: `app/api/*.py` を `/api/v1` 配下に集約
- Celery ワーカー
  - ブローカー/バックエンド: Redis（`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`）
  - タスク定義: `app/workers/tasks.py`（CSV の取り出し→LLM 分析→DB 登録）
- データベース
  - SQLAlchemy + Alembic
  - 既定: `sqlite:///./app_dev.sqlite3`（`DATABASE_URL` で Postgres 等に差し替え）
- ストレージ
  - Local or S3（`UPLOAD_BACKEND`=local/s3）
  - URI 形式: `local://...` または `s3://bucket/key`
- LLM 連携
  - プロバイダー: mock / generic / openai / azure_openai（デフォルトは mock）
  - 環境変数で接続やモデル指定、タイムアウト等を制御

主要フロー
----------
1) CSV アップロード→非同期解析キュー投入
  - エンドポイント: `POST /api/v1/uploads`
  - 実装: `app/api/upload.py::upload_and_enqueue_analysis`
  - 概要:
    - CSV を受領し `validate_csv_or_raise` で体裁検証
    - ストレージへ保存（Local/S3）
    - `uploaded_file` レコードを作成（ステータス: QUEUED）
    - Celery タスク `process_uploaded_file` へ `file_id` を投入

2) バックグラウンド解析
  - 実装: `app/workers/tasks.py::process_uploaded_file`
  - 概要:
    - `uploaded_file.s3_key` から CSV をロード
    - `analyze_and_store_comments` を呼び出し
      - 1 行に対して `SurveyResponse`（数値評価）を作成
      - 任意/必須の自由記述列を `Comment` として保存
      - LLM 分析（対象列のみ）を実行し分類/要約/重要度などを記録
    - 成功時: `uploaded_file` を COMPLETED に更新（処理件数等を更新）
    - 例外時: リトライ/FAILED マーク/エラーログ

3) 進捗・結果参照
  - 進捗: `GET /api/v1/uploads/{file_id}/status`（`AnalysisStatusResponse`）
  - コメント一覧: `GET /api/v1/courses/{course_name}/comments`
  - メトリクス参照/更新: `GET/PUT /api/v1/uploads/{file_id}/metrics`
  - 講義マスタ CRUD: `POST/PUT /api/v1/lectures`, 一覧: `GET /api/v1/courses`

API 概要
--------
- uploads（`app/api/upload.py`）
  - `GET /uploads/check-duplicate`: 講義（講座名/日付/回）の重複確認
  - `POST /uploads`: CSV アップロード & 非同期解析のキュー投入
  - `DELETE /uploads/{file_id}`: 解析結果/レコードの削除（必要に応じ）
  - `POST /uploads/{file_id}/finalize`: 暫定→確定の確定処理（必要に応じ）
- analysis（`app/api/analysis.py`）
  - `GET /uploads/{file_id}/status`: 処理ステータス/件数/時刻/エラー情報
- comments（`app/api/comments.py`）
  - `GET /courses/{course_name}/comments`: 最新のコメント分析一覧（任意で version 絞込）
- courses（`app/api/courses.py`）
  - `GET /courses`: 講義一覧（検索/ソート可、lecture テーブル優先、無ければ uploaded_file から推定）
- lectures（`app/api/lectures.py`）
  - `POST /lectures`, `PUT /lectures/{lecture_id}`: 講義マスタの作成/更新（重複整合性チェックあり）
- metrics（`app/api/metrics.py`）
  - `GET/PUT /uploads/{file_id}/metrics`: Zoom 参加者/録画視聴数の参照/更新

データモデル（`app/db/models.py`）
---------------------------------
- `uploaded_file`
  - 講義の複合識別子: `course_name`, `lecture_date`, `lecture_number`
  - ステータス: QUEUED/PROCESSING/COMPLETED/FAILED
  - ストレージキー: `s3_key`（local/s3 URI）
  - 件数フィールド: `total_rows`, `processed_rows`
  - タスク連携/時刻系: `task_id`, `processing_started_at`, `processing_completed_at`, `finalized_at`
  - Unique 制約: `(course_name, lecture_date, lecture_number)`
- `survey_response`
  - 数値評価の 1 行分。`file_id` に紐づく
  - 個人属性（`account_id`, `account_name`）と多数のスコアカラムを保持
- `comment`
  - 自由記述コメント。`file_id` と `survey_response_id` を参照
  - LLM 出力（カテゴリ/感情/要約/重要度/リスク等）と `processed_at`, `analysis_version`
- `lecture_metrics`
  - `file_id` にユニークで紐づくメトリクス（参加者数、視聴数、`updated_at`）
- `lecture`
  - 講義マスタ（`course_name`, `academic_year`, `period`, `category`）
  - Unique 制約: `(course_name, academic_year, period)`
- マイグレーション: `alembic/versions/`
  - 初期作成（`6185d09e3ea8_*`）にスキーマの大半
  - 追補（`1f9ed4bcbe87_*`）は No-Op（初期に包含済み）

ストレージ層（`app/services/storage.py`）
---------------------------------------
- `get_storage_client()` によりバックエンドを選択
  - local: `UPLOAD_LOCAL_DIRECTORY` 配下に保存、URI は `local://...`
  - s3: `UPLOAD_S3_BUCKET` と `UPLOAD_BASE_PREFIX` を使用、URI は `s3://bucket/prefix/key`
- セキュリティ
  - パス結合は `_safe_join` でディレクトリトラバーサルを防止
  - S3 は例外を捕捉し `StorageError` に正規化

LLM 連携（`app/services/llm_client.py`, `app/analysis/*`）
-------------------------------------------------------
- 設定は `LLM_*` 環境変数からロード（`app/core/settings.py`）
- 既定は `provider=mock`（外部 API なしでテスト可能）
- `analyzer.analyze_comment` が以下を統合:
  - LLM 出力（カテゴリ/要約/重要度/リスク/感情）
  - 安全性チェック（誹謗中傷/リスク評価）
  - キーワードベースのカテゴリ/感情補助分類（`aggregation.py`）
  - 重要度スコア正規化（`scoring.py`）

CSV バリデーションと取り込み（`app/services/upload_pipeline.py`）
------------------------------------------------------------
- 文字コード: UTF-8（BOM 許容）
- ヘッダ必須: 空/重複はエラー
- 自由記述列: 先頭が「（任意）」または「【必須】」で始まる列のみ対象
- 数値スコア列: 固定マッピングで `SurveyResponse` に格納
- アカウント情報: `アカウントID`/`アカウント名`（スペース揺れや英語キーも許容）
- LLM 対象: 「（任意）」で始まる列のみ（非対象はスキップし `warnings` に記録）

バックグラウンド処理（`app/workers/*`）
--------------------------------------
- Celery 設定は `CELERY_*` から（`task_always_eager` 等で同期実行も可能）
- 失敗時のリトライと最終的な FAILED マーク処理（ストレージ/検証エラー別）
- タスク完了時に `uploaded_file` の処理件数/時刻を更新

設定と環境変数（`app/core/settings.py`）
--------------------------------------
- 共通: `.env` を読込（pydantic-settings）
- 主要キー
  - `DATABASE_URL`: DB 接続（例: `postgresql://user:password@db:5432/aiedx`）
  - `UPLOAD_BACKEND`: `local` | `s3`
  - `UPLOAD_LOCAL_DIRECTORY`: ローカル保存先（既定: `./var/uploads`）
  - `UPLOAD_S3_BUCKET`, `UPLOAD_BASE_PREFIX`, `AWS_*`: S3/AWS 資格情報
  - `LLM_*`: プロバイダー/エンドポイント/モデル/API キー/タイムアウト 等
  - `CELERY_*`: ブローカー/タスク設定
  - `API_TITLE`, `API_DEBUG`, `APP_ENV`

インフラ・実行（Docker / docker-compose / AWS CDK）
-----------------------------------------------
- Dockerfile
  - Python 3.11 slim, `requirements.txt` をインストール、Uvicorn で起動
- docker-compose.yml
  - `api`（FastAPI）・`worker`（Celery）・`db`（Postgres）・`redis`
  - `.env` 読込 + 必須環境変数明示、ローカル開発用にポート公開
- AWS CDK（任意の参考）
  - ECS on Fargate（ALB, ECR, VPC, CloudWatch Logs）
  - HealthCheck: `/health` を ALB ターゲットグループに設定

運用・監視の要点
----------------
- ヘルスチェック: `GET /health`（アプリの起動状態）
- ログ: CSV 行/抽出値/DB 保存前後/LLM 警告などを INFO/WARNING で記録
- エラーハンドリング: ストレージ/CSV/DB/外部 API をそれぞれ `HTTPException` として返却 or `StorageError` 等で正規化
- 冪等性/整合性:
  - `(course_name, lecture_date, lecture_number)` のユニーク制約で重複アップロードを抑止
  - `lecture` テーブルのユニーク制約による重複防止

付記
----
- 既定では LLM プロバイダーは `mock` のため、外部接続なしで動作確認可能です。
- `task_always_eager=true` を用いると Celery が同期実行となり、開発時の動作確認が容易です。
- 本ドキュメントはソース（`app/` 配下）に準拠しています。変更時は本書も更新してください。


