# AIE-DXproject バックエンド

FastAPIで構築されたAIE-DXprojectイニシアティブのバックエンドサービス。

## 要件

- Docker および Docker Compose v2
- Make（便利なコマンド用、オプション）

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

## プロジェクト構造

```
.
├── app.py
├── tests/
│   └── test_health.py
├── infra/
│   ├── app.py
│   ├── README.md
│   ├── requirements.txt
│   ├── cdk.json
│   ├── cdk.context.json
│   ├── cdk.out/                # CDK synth 後に生成される一時成果物
│   ├── stacks/
│   │   ├── backend_stack.py
│   │   └── github_oidc_role_stack.py
│   └── tests/
│       └── test_synth.py
├── .github/
│   └── workflows/
│       └── ci.yml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .env.example
└── .gitignore
```

ローカル開発用の仮想環境 `.venv/` や CDK 実行時に生成される `infra/cdk.out/` などは Git 管理対象外です。

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
