# Infra (AWS CDK)

このディレクトリには、バックエンドを Amazon ECS on Fargate 上で稼働させるための AWS インフラを Python 製 AWS CDK で定義するコードを配置します。

## 前提条件

- Node.js 18+
- Python 3.11+
- AWS CLI (認証済み)
- AWS CDK v2 (`npm install -g aws-cdk`)

## セットアップ手順

```bash
cd infra
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

環境が整ったら、CDK アプリの合成とデプロイを行えます。

```bash
cdk synth                             # CloudFormation テンプレートを生成
cdk bootstrap --context account=xxx --context region=ap-northeast-1
cdk deploy   --context account=xxx --context region=ap-northeast-1
```

※ `account` / `region` は実際にデプロイする AWS アカウントに置き換えてください。AWS 環境変数
`CDK_DEFAULT_ACCOUNT` / `CDK_DEFAULT_REGION` を設定している場合は `--context` は省略可能です。

`cdk.json` の `github_owner` / `github_repo` を自身の GitHub リポジトリに更新するか、コマンド実行時に `--context github_owner=xxx --context github_repo=yyy` を指定してください。

## スタックの概要

- VPC（2AZ, パブリック/プライベートサブネット）
- ECR リポジトリ（Docker イメージ用）
- ECS クラスター（Fargate キャパシティ）
- Application Load Balanced Fargate Service（FastAPI コンテナを想定）
- 出力情報（サービスのURL、ECRリポジトリURIなど）

## GitHub Actions 用 IAM ロール

`GithubOidcRoleStack` は GitHub Actions から AWS を操作するための OIDC 対応 IAM ロールとプロバイダーを作成します。

```bash
cdk deploy AieDxprojectGithubOidcStack \
  --context account=xxx \
  --context region=ap-northeast-1 \
  --context github_owner=あなたのGitHub組織orユーザー名 \
  --context github_repo=あなたのリポジトリ名
```

デプロイ結果に表示される `GithubActionsRoleArn` を GitHub リポジトリシークレット `AWS_DEPLOY_ROLE_ARN` に登録してください。

デフォルトでは検証用に公開 Nginx イメージを利用してデプロイされます。独自イメージを利用する場合は CDK 実行時に下記のコンテキストを指定してください。

```bash
cdk deploy AieDxprojectBackendStack \
  --context account=xxx \
  --context region=ap-northeast-1 \
  --context use_sample_image=false \
  --context image_tag=latest
```

`image_tag` は ECR リポジトリにプッシュされたタグに合わせて変更してください。

## Lint / テスト

```bash
pytest
```

（テストは今後必要に応じて追加）

## GitHub Actions との連携

- ルートリポジトリの `.github/workflows/ci.yml` では、`main` ブランチへの push 時に Docker イメージをビルドして ECR へプッシュします。
- `AWS_DEPLOY_ROLE_ARN` シークレットに OIDC で Assume する IAM ロールを登録し、ECR と ECS 更新の権限を付与してください。
- CDK デプロイ後は、パイプラインでプッシュされたイメージを使用するため、ECS サービスの `desired_count` を 1 以上に更新し、ALB エンドポイントで FastAPI の `/health` を確認してください。
