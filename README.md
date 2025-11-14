# AIE-DXプロジェクト１（バックエンド）

FastAPIで構築されたAIE-DXprojectイニシアティブのバックエンドサービス。

## クイックスタート

```bash
docker compose up --build
```

http://localhost:8000/docs にアクセスしてインタラクティブなAPIドキュメントを探索してください。スタックを停止するには `docker compose down` を使用してください。

## 開発ワークフロー

- 環境固有のシークレットはローカルの `.env` ファイルに保存してください。
- 要件が変更された際は `docker compose up --build` を実行して依存関係を再ビルドしてください。
- 変更をプッシュする前に `pytest`（コンテナ内または仮想環境内）を実行してテストを実行してください。
- インフラの変更は `infra/README.md` を参照し、AWS CDK を使って管理してください。

## 設定・機密情報管理

Pydantic Settings（`app/core/settings.py`）を使ってアプリ構成値と機密情報を一元管理しています。`.env` に記述した値は自動的にロードされ、`AppSettings` 経由でFastAPIや各サービスに渡されます。

- `DATABASE_URL`: RDBの接続情報。未設定の場合はローカル用のSQLiteにフォールバックします。
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`: AWS SDKやCDKが利用する認証情報。
- `LLM_*`: LLM連携に必要な各種パラメータ（詳細は後述）。
- `UPLOAD_BACKEND`, `UPLOAD_S3_BUCKET`, `UPLOAD_BASE_PREFIX`, `UPLOAD_LOCAL_DIRECTORY`: アップロード済みCSVの保存先を制御します。デフォルトはローカルディスク（`local`）に保存し、`s3` を指定するとS3アップロードが有効になります。

### データベースマイグレーション（Alembic）

SQLAlchemyモデルの変更は Alembic を使って管理します。初回セットアップまたはスキーマ更新時は以下を実行してください。

```bash
alembic upgrade head
```

差分からマイグレーションスクリプトを生成する場合は `alembic revision --autogenerate -m "message"` を使用します。生成後は内容を確認し、バージョン管理にコミットしてください。

`.env` はリポジトリにコミットしないでください（`.gitignore` で除外済み）。共有が必要な場合は、`.env.example` をコピーして個々の環境で値を設定してください。

## LLM 連携設定

コメント分析には任意のLLM APIを利用できます。`LLM_PROVIDER` を `mock`（デフォルト）、`openai`、`azure_openai`、`generic` から選択し、必要に応じて以下の環境変数を `.env` へ設定してください。

- `LLM_API_BASE`: APIエンドポイントのベースURL（`mock`以外では必須）
- `LLM_MODEL`: 使用するモデル名
- `LLM_API_KEY`: 認証に使用するAPIキー（必要な場合）
- `LLM_API_VERSION`: Azure OpenAI利用時のAPIバージョン
- `LLM_TIMEOUT_SECONDS`: タイムアウト秒数（デフォルト15秒）
- `LLM_REQUEST_TEMPLATE`: LLMに与えるプロンプトをカスタマイズしたい場合に設定
- `LLM_EXTRA_HEADERS`: 追加ヘッダーをJSON文字列で指定

`mock` モードでは外部通信を行わず、テスト用の固定レスポンスを返します。`openai` / `azure_openai` を利用する場合は、必ず `LLM_API_BASE` や認証情報を設定してください。また、本リリースで `comment` テーブルに `llm_importance_level` / `llm_importance_score` / `llm_risk_level` カラムを追加したため、既存DBを利用する場合はマイグレーションを適用する必要があります。アプリケーション起動時に不足している列は自動で `ALTER TABLE` により追加されます。

## プロジェクト構造

```
.
├── app/                     # FastAPIアプリケーションパッケージ
│   ├── __init__.py          # app, create_app を公開
│   └── main.py              # FastAPI本体とルート定義
├── tests/                   # アプリ用ユニットテスト
│   ├── test_health.py       # ヘルスチェックエンドポイントのテスト
│   ├── test_llm_client.py   # LLMクライアントのテスト
│   ├── test_migrations.py   # マイグレーションユーティリティの検証
│   ├── test_settings.py     # 設定読み込みの検証
│   └── test_storage.py      # アップロードストレージの検証
├── alembic/                 # Alembic 設定とマイグレーションスクリプト
│   ├── env.py               # マイグレーション実行時の設定
│   └── versions/            # 生成されたマイグレーションファイル
├── infra/                   # AWS CDK によるインフラコード
│   ├── app.py               # CDKエントリーポイント
│   ├── README.md            # インフラ運用手順
│   ├── requirements.txt     # CDK依存パッケージ
│   ├── cdk.json             # CDKアプリの設定
│   ├── cdk.context.json     # デプロイ時に保存されたコンテキスト
│   ├── cdk.out/             # CDK synth 後の生成物（Git管理外推奨）
│   ├── stacks/              # スタック定義
│   │   ├── backend_stack.py       # ECS Fargate本番スタック
│   │   └── github_oidc_role_stack.py # GitHub Actions用IAMロール
│   └── tests/               # CDKスタックの検証テスト
│       └── test_synth.py    # テンプレート生成テスト
├── .github/workflows/       # GitHub Actions ワークフロー
│   └── ci.yml               # フォーマット・テスト・ECRデプロイ
├── Dockerfile               # 本番/ローカル用ビルドレシピ
├── docker-compose.yml       # ローカル開発用コンテナ起動設定
├── requirements.txt         # アプリケーション依存パッケージ
├── requirements-dev.txt     # 開発・テスト用依存パッケージ
├── pyproject.toml           # フォーマッタ/pytest 設定
├── .env.example             # 必須環境変数のサンプル
└── .gitignore               # Git 管理対象から除外する項目
```

ローカル開発用の仮想環境 `.venv/` や CDK 実行時に生成される `infra/cdk.out/` などは Git 管理対象外です。

## システムアーキテクチャ

### 全体構成図

```mermaid
graph TB
    subgraph "クライアント層"
        Client[Web/API クライアント]
    end
    
    subgraph "API層"
        FastAPI[FastAPI アプリケーション<br/>app/main.py]
        Router1[Upload Router<br/>/api/v1/uploads]
        Router2[Analysis Router<br/>/api/v1/uploads/{id}/status]
        Router3[Comments Router<br/>/api/v1/courses/{name}/comments]
        Router4[Courses Router<br/>/api/v1/courses]
        Router5[Lectures Router<br/>/api/v1/lectures]
        Router6[Metrics Router<br/>/api/v1/uploads/{id}/metrics]
    end
    
    subgraph "サービス層"
        Storage[Storage Service<br/>Local/S3]
        LLMClient[LLM Client<br/>OpenAI/Azure/Mock]
        Pipeline[Upload Pipeline<br/>CSV解析・検証]
    end
    
    subgraph "バックグラウンド処理"
        Celery[Celery Worker]
        Redis[Redis<br/>メッセージブローカー]
        Task[process_uploaded_file<br/>非同期分析タスク]
    end
    
    subgraph "データ層"
        DB[(PostgreSQL/SQLite<br/>データベース)]
        Models[SQLAlchemy Models<br/>UploadedFile/Comment/SurveyResponse/Lecture]
    end
    
    subgraph "外部サービス"
        S3[AWS S3<br/>オプション]
        LLMAPI[LLM API<br/>OpenAI/Azure等]
    end
    
    Client --> FastAPI
    FastAPI --> Router1
    FastAPI --> Router2
    FastAPI --> Router3
    FastAPI --> Router4
    FastAPI --> Router5
    FastAPI --> Router6
    
    Router1 --> Storage
    Router1 --> DB
    Router1 --> Redis
    
    Router2 --> DB
    Router3 --> DB
    Router4 --> DB
    Router5 --> DB
    Router6 --> DB
    
    Redis --> Celery
    Celery --> Task
    Task --> Storage
    Task --> Pipeline
    Task --> LLMClient
    Task --> DB
    
    Pipeline --> LLMClient
    Storage --> S3
    LLMClient --> LLMAPI
    
    Models --> DB
```

### データフロー図（アップロード・分析フロー）

```mermaid
sequenceDiagram
    participant Client as クライアント
    participant API as FastAPI API
    participant Storage as Storage Service
    participant DB as データベース
    participant Redis as Redis Queue
    participant Worker as Celery Worker
    participant Pipeline as Upload Pipeline
    participant LLM as LLM Client
    participant LLMAPI as LLM API

    Client->>API: POST /api/v1/uploads<br/>(CSV + メタデータ)
    API->>API: CSV検証<br/>(validate_csv_or_raise)
    API->>Storage: ファイル保存<br/>(save)
    Storage-->>API: ストレージURI
    API->>DB: UploadedFile作成<br/>(status=QUEUED)
    API->>Redis: タスクエンキュー<br/>(process_uploaded_file.delay)
    API-->>Client: レスポンス<br/>(file_id, status=QUEUED)

    Redis->>Worker: タスク取得
    Worker->>DB: ステータス更新<br/>(status=PROCESSING)
    Worker->>Storage: CSV読み込み<br/>(load)
    Storage-->>Worker: CSVバイトデータ
    
    loop 各行を処理
        Worker->>Pipeline: CSV解析・行抽出
        Pipeline->>DB: SurveyResponse作成
        Pipeline->>Pipeline: コメント抽出<br/>（任意）/【必須】列
        
        alt LLM分析対象（任意）列
            Pipeline->>LLM: コメント分析リクエスト
            LLM->>LLMAPI: API呼び出し
            LLMAPI-->>LLM: 分析結果
            LLM-->>Pipeline: 構造化結果
        else 必須列
            Pipeline->>Pipeline: LLM分析スキップ
        end
        
        Pipeline->>Pipeline: 重要度スコア計算<br/>安全性チェック<br/>カテゴリ分類
        Pipeline->>DB: Comment作成<br/>(分析結果含む)
    end
    
    Worker->>DB: ステータス更新<br/>(status=COMPLETED)
    
    Client->>API: GET /api/v1/uploads/{id}/status
    API->>DB: ステータス照会
    DB-->>API: 処理状況
    API-->>Client: ステータスレスポンス
```

### データベースER図

```mermaid
erDiagram
    UploadedFile ||--o{ Comment : "has"
    UploadedFile ||--o{ SurveyResponse : "has"
    UploadedFile ||--|| LectureMetrics : "has"
    UploadedFile }o--|| Lecture : "references"
    SurveyResponse ||--o{ Comment : "has"
    
    UploadedFile {
        int file_id PK
        string course_name
        date lecture_date
        int lecture_number
        string status
        string s3_key
        timestamp upload_timestamp
        string original_filename
        int total_rows
        int processed_rows
        timestamp processing_started_at
        timestamp processing_completed_at
        text error_message
        int lecture_id FK
    }
    
    Comment {
        int id PK
        int file_id FK
        int survey_response_id FK
        string account_id
        string account_name
        text question_text
        text comment_text
        string llm_category
        string llm_sentiment
        text llm_summary
        string llm_importance_level
        float llm_importance_score
        string llm_risk_level
        timestamp processed_at
        string analysis_version
    }
    
    SurveyResponse {
        int id PK
        int file_id FK
        string account_id
        string account_name
        int score_satisfaction_overall
        int score_satisfaction_content_volume
        int score_satisfaction_content_understanding
        int score_satisfaction_content_announcement
        int score_satisfaction_instructor_overall
        int score_satisfaction_instructor_efficiency
        int score_satisfaction_instructor_response
        int score_satisfaction_instructor_clarity
        int score_self_preparation
        int score_self_motivation
        int score_self_applicability
        int score_recommend_to_friend
    }
    
    Lecture {
        int id PK
        string course_name
        int academic_year
        string period
        string category
    }
    
    LectureMetrics {
        int id PK
        int file_id FK
        int zoom_participants
        int recording_views
        timestamp updated_at
    }
```

### コンポーネント依存関係図

```mermaid
graph LR
    subgraph "app/main.py"
        Main[create_app<br/>FastAPI Factory]
    end
    
    subgraph "app/api/"
        Upload[upload.py]
        Analysis[analysis.py]
        Comments[comments.py]
        Courses[courses.py]
        Lectures[lectures.py]
        Metrics[metrics.py]
    end
    
    subgraph "app/services/"
        StorageSvc[storage.py<br/>LocalStorageClient<br/>S3StorageClient]
        LLMSvc[llm_client.py<br/>LLMClient]
        PipelineSvc[upload_pipeline.py<br/>CSV解析・検証]
    end
    
    subgraph "app/analysis/"
        Analyzer[analyzer.py<br/>analyze_comment]
        Aggregation[aggregation.py<br/>分類・感情分析]
        Safety[safety.py<br/>安全性チェック]
        Scoring[scoring.py<br/>重要度スコア]
        LLMAnalyzer[llm_analyzer.py<br/>LLM分析ラッパー]
    end
    
    subgraph "app/workers/"
        CeleryApp[celery_app.py<br/>Celery設定]
        Tasks[tasks.py<br/>process_uploaded_file]
    end
    
    subgraph "app/db/"
        Models[models.py<br/>SQLAlchemy Models]
        Session[session.py<br/>get_db]
    end
    
    subgraph "app/core/"
        Settings[settings.py<br/>AppSettings]
    end
    
    Main --> Upload
    Main --> Analysis
    Main --> Comments
    Main --> Courses
    Main --> Lectures
    Main --> Metrics
    
    Upload --> StorageSvc
    Upload --> PipelineSvc
    Upload --> Session
    Upload --> Models
    Upload --> Tasks
    
    Analysis --> Session
    Analysis --> Models
    
    Comments --> Session
    Comments --> Models
    
    Courses --> Session
    Courses --> Models
    
    Lectures --> Session
    Lectures --> Models
    
    Metrics --> Session
    Metrics --> Models
    
    Tasks --> StorageSvc
    Tasks --> PipelineSvc
    Tasks --> Session
    Tasks --> Models
    
    PipelineSvc --> Analyzer
    PipelineSvc --> Models
    
    Analyzer --> LLMAnalyzer
    Analyzer --> Aggregation
    Analyzer --> Safety
    Analyzer --> Scoring
    
    LLMAnalyzer --> LLMSvc
    
    StorageSvc --> Settings
    LLMSvc --> Settings
    CeleryApp --> Settings
    Session --> Settings
    
    Settings --> Models
```

## コントリビューション

1. フィーチャーブランチを作成してください。
2. Blackとisortでコードをフォーマットしてください（`black . && isort .`）。
3. `pytest`を実行してください。
4. mainブランチへのプルリクエストを開いてください。

## CI/CD

- GitHub Actions は `pull_request` と `main` への push で formatter / テストを実行し、`infra/tests` も検証します。
- `main` ブランチに push された変更は、`publish-image` ジョブで Docker イメージをビルドし Amazon ECR (`aie-dxproject-backend`) にプッシュします。
- OIDC で Assume する IAM ロール ARN を `AWS_DEPLOY_ROLE_ARN` シークレットに設定してください。ロールには `AmazonEC2ContainerRegistryPowerUser` 相当の権限と、ECS サービス更新用の権限を付与する必要があります。
- CDK デプロイ時は `infra/README.md` を参照し、独自のイメージを使う場合は `use_sample_image=false` と `image_tag` をコンテキストに指定してください。
- GitHub Actions 向け IAM ロールは `AieDxprojectGithubOidcStack` で作成できます。出力されたロール ARN を GitHub シークレットに登録してください。
