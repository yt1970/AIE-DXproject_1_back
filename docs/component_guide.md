# バックエンド コンポーネントガイド

リポジトリ全体の概要まとめです。処理フローや詳細設計は `docs/backend_system_design.md` を併読してください。

## 目次
- app/api
- app/analysis
- app/services
- app/db
- app/workers
- app/core
- infra
- scripts / tests

## app/api （FastAPI ルーター）
- upload.py: CSVアップロード受付、重複チェック、削除、preliminary→final固定化。
- analysis.py: アップロード単位の処理ステータス参照（Celeryキューの進捗）。
- comments.py: 講義名ベースのコメント一覧取得（analysis_version指定可）。
- courses.py: 講義一覧（lectureテーブル優先、無ければuploaded_fileから推定）。
- lectures.py: 講義マスタのCRUDと関連データ削除。
- metrics.py: lecture/file単位のZoom参加者数・録画視聴数の参照/更新。
- dashboard.py: 簡易ダッシュボード集計（平均スコア/NPS/感情/カテゴリ）。前計算テーブルは未使用。

## app/analysis （LLM & 集約ロジック）
- analyzer.py: コメント1件の総合分析。LLM呼び出し・安全性チェック・重要度計算・感情/カテゴリ正規化を統合。
- llm_analyzer.py: LLMクライアントを複数タスク（sentiment/importance/category/risk/full）で呼び分け、結果をマージ。
- aggregation.py: キーワードによるカテゴリ/感情の補助分類。
- safety.py / scoring.py: 誹謗中傷判定・重要度スコア決定。
- prompts/: LLMへの指示テンプレート。

## app/services （周辺サービス）
- llm_client.py: LLM呼び出しラッパー。`LLM_PROVIDER=mock|openai|azure_openai|generic` に対応。デフォルトはmock。
- upload_pipeline.py: CSV検証→行単位の解析→DB登録。`（任意）` 列のみLLM分析を実行し、`comment`/`survey_response` に書き込む。
- storage.py（READMEで紹介）: Local/S3の保存/読込/削除を抽象化。
- __init__.py: ストレージクライアントのファクトリ等。

## app/db （データモデル・マイグレーションユーティリティ）
- models.py: 現在利用中のテーブル定義  
  - uploaded_file（アップロード管理、status/時刻/task_id等を保持）  
  - survey_response（数値回答1行分）  
  - comment（自由記述 + LLM結果を直格納）  
  - lecture（講義マスタ）  
  - lecture_metrics（講義回の参加者数・視聴数）  
- migrations.py: 起動時の不足カラム自動追加（SQLite/既存DB用）。旧スキーマのクリーンアップも含む。
- alembic/: 初期マイグレーションは旧モデル（lectures/submissions等）を含むので、実スキーマとの差異に注意。

## app/workers （非同期処理）
- tasks.py: `process_uploaded_file` Celeryタスク。CSVを読み込み、`survey_response`/`comment` を生成し、処理件数を更新。
- celery_app.py: Celery設定（ブローカー/リトライなど）。

## app/core
- settings.py: Pydantic Settings。DB/LLM/Storage/Celery設定を環境変数からロード。

## infra
- AWS CDK サンプルスタック（ECS on Fargate 等）。本番インフラを管理する場合はここを参照。

## scripts / tests
- scripts/: 補助スクリプト（必要に応じて確認）。
- tests/: ヘルスチェック、LLMクライアント、マイグレーション等のユニットテスト。

## 関連ドキュメント
- docs/backend_system_design.md: データフロー、コンポーネント依存、設定一覧を詳細に記載。
