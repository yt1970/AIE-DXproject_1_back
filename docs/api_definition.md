# AIE-DXproject API定義書

## 1. 概要
- **アプリケーション名**: AIE-DXproject Backend  
- **API仕様バージョン**: 1.0.0 (`app/main.py`)  
- **ベースURL**: `http://<host>:8000`（ローカル開発では `docker compose up` 後に `http://localhost:8000`）  
- **認証/認可**: 現状なし。導入時は本書を改訂する。  
- **データ形式**: JSON（`POST /api/v1/uploads` は `multipart/form-data` を使用）  
- **文字コード**: UTF-8（アップロードCSVも UTF-8 必須）

## 2. 共通仕様

### 2.1 日付・日時表記
- 日付: ISO 8601（例: `2024-04-15`）。`UploadRequestMetadata.lecture_date` が該当。  
- 日時: ISO 8601（例: `2024-04-15T09:30:00.123456`）。`/health` の `timestamp` や `comment.processed_at` などで使用。

### 2.2 エラーレスポンス
- FastAPI の `HTTPException` を利用。基本形は `{"detail": "<メッセージ>"}`。  
- バリデーションエラー時（422）は Pydantic 標準の詳細レスポンスが返る。

### 2.3 代表的なステータスコード
| ステータス | 説明 | 主な発生箇所 |
|-----------|------|--------------|
| 200 OK | 正常終了 | 全エンドポイント |
| 400 Bad Request | リクエスト不備 | CSV 読込失敗、必須列欠落、重複ヘッダーなど |
| 404 Not Found | リソース未存在 | `GET /api/v1/uploads/{file_id}/status` |
| 422 Unprocessable Entity | バリデーション失敗 | `metadata` JSON の形式不正など |
| 500 Internal Server Error | サーバー側エラー | ストレージ保存失敗、DBエラー |

### 2.4 エンドポイント一覧
| 分類 | メソッド | パス | 説明 |
|------|----------|------|------|
| System | GET | `/health` | アプリケーションの稼働確認 |
| Upload | POST | `/api/v1/uploads` | 受講生コメントCSVのアップロードと同期分析 |
| Analysis | GET | `/api/v1/uploads/{file_id}/status` | アップロード済みファイルの分析ステータス参照 |
| Results | GET | `/api/v1/courses/{course_name}/comments` | 講義別の分析済みコメント一覧取得 |

## 3. エンドポイント詳細

### 3.1 ヘルスチェック
- **メソッド / パス**: `GET /health`
- **概要**: アプリケーションの稼働状態と現在時刻を返す。監視や Liveness Probe に利用。
- **認証**: なし
- **リクエストボディ**: なし
- **レスポンス 200**
```json
{
  "status": "ok",
  "timestamp": "2024-04-15T09:30:00.123456",
  "app_name": "AIE-DXproject Backend",
  "environment": "local"
}
```
- **想定エラー**: 特になし（内部例外発生時は 500）

---

### 3.2 CSVアップロード & 同期分析
- **メソッド / パス**: `POST /api/v1/uploads`
- **概要**: 講義関連のコメントCSVを受け取り、任意コメント列だけを抽出して LLM 分析を実施。結果は `comment` テーブルに保存され、処理統計が `uploaded_file` に記録される。
- **認証**: なし
- **コンテントタイプ**: `multipart/form-data`
- **フィールド構成**
  - `file`: CSV ファイル（必須）  
    - 1 行目のヘッダーから **「（任意）」で始まる列** だけを分析対象として抽出  
    - `【必須】受講生が学んだこと` などの必須列は自動的に無視される
  - `metadata`: JSON 文字列（必須）。`UploadRequestMetadata` に準拠。

| metadataキー | 型 | 必須 | 説明 |
|--------------|----|------|------|
| `course_name` | string | ○ | 講義名。ストレージパスの一部に使用。 |
| `lecture_date` | date | ○ | 講義日（ISO 8601）。 |
| `lecture_number` | integer | ○ | 講義回。 |
| `uploader_id` | integer | 任意 | アップロード実施者の識別子。 |

- **処理概要**
  1. `metadata` を検証し `uploaded_file` レコードを `PENDING` 状態で作成。
  2. CSV のヘッダーから「（任意）…」列を収集。該当列が無い場合は 400 を返す。
  3. CSV を UTF-8 で読み込み、対象列のセル値を走査。空白セルはスキップ。
  4. 取得した各コメントテキストを `analyze_comment` に渡し、LLM 構造化結果を受け取る。
  5. コメント毎に `comment` レコードを作成し、分析結果を保存。
  6. 処理完了後、`uploaded_file.status` を `COMPLETED` に更新し、`total_rows`/`processed_rows` にコメント件数を記録。

- **成功レスポンス 200 (`UploadResponse`)**
```json
{
  "file_id": 42,
  "status_url": "/api/v1/uploads/42/status",
  "message": "Upload and analysis successful."
}
```

- **サンプルリクエスト（curl）**
```bash
curl -X POST http://localhost:8000/api/v1/uploads \
  -F 'file=@comments.csv;type=text/csv' \
  -F 'metadata={
        "course_name": "DX Bootcamp",
        "lecture_date": "2024-04-15",
        "lecture_number": 3,
        "uploader_id": 1001
      }'
```
※ `comments.csv` の例（ヘッダーのみ抜粋）
```
【必須】受講生が学んだこと,（任意）講義全体のコメント,（任意）講師へのメッセージ
```

- **主なエラーレスポンス**
| ステータス | detail 例 | 発生条件 |
|------------|-----------|----------|
| 400 | `"Uploaded file is empty."` | ファイル中身が空 |
| 400 | `"CSV header contains duplicate column names after normalization."` | ヘッダー名重複 |
| 400 | `"CSV must contain at least one column whose header starts with '（任意）'."` | 分析対象列が無い |
| 400 | `"CSV must be UTF-8 encoded: ..."` | 文字コード不正 |
| 422 | `"Invalid metadata format: ..."` | `metadata` JSON のパース失敗/検証エラー |
| 500 | `"Failed to persist uploaded file."` | ストレージ保存失敗 |
| 500 | `"Error during analysis process: ..."` | DB トランザクション中の例外 |

---

### 3.3 アップロードステータス取得
- **メソッド / パス**: `GET /api/v1/uploads/{file_id}/status`
- **概要**: 指定ファイルの分析状況と処理件数を返す。
- **パスパラメータ**
  - `file_id` (integer, 必須): アップロード時に返却されたID。
- **レスポンス 200 (`AnalysisStatusResponse`)**
```json
{
  "file_id": 42,
  "status": "COMPLETED",
  "total_comments": 250,
  "processed_count": 250
}
```
  - `status`: `PENDING` / `COMPLETED` / `FAILED`
  - `total_comments`: 抽出したコメント件数
  - `processed_count`: LLM 処理完了件数（`processed_rows`。NULL 時は `comment` テーブル件数で補完）

- **エラー**
| ステータス | detail 例 | 発生条件 |
|------------|-----------|----------|
| 404 | `"File with id 42 not found"` | 指定IDの `uploaded_file` が存在しない |

---

### 3.4 講義別コメント分析一覧
- **メソッド / パス**: `GET /api/v1/courses/{course_name}/comments`
- **概要**: 指定講義に紐づくコメント分析結果をリストで返す。`uploaded_file.course_name` をキーに `comment` と結合。
- **パスパラメータ**
  - `course_name` (string, 必須): 講義名。完全一致で検索。
- **クエリパラメータ**
| パラメータ | 型 | 必須 | デフォルト | 説明 |
|------------|----|------|------------|------|
| `limit` | integer | 任意 | 100 | 取得件数の最大値。 |
| `skip` | integer | 任意 | 0 | スキップする件数（ページネーション用）。 |

- **レスポンス 200**: `CommentAnalysisSchema` の配列。主なフィールドは以下。
| フィールド | 型 | 説明 |
|------------|----|------|
| `comment_text` | string | 分析対象となったコメント原文 |
| `llm_category` | string/null | LLM分類カテゴリ |
| `llm_sentiment` | string/null | 推定センチメント |
| `llm_summary` | string/null | 要約（LLM不在時は原文の切り詰め） |
| `llm_importance_level` | string/null | 重要度レベル（例: `low`/`medium`/`high`） |
| `llm_importance_score` | number/null | 重要度スコア（0.0〜1.0） |
| `llm_risk_level` | string/null | リスクレベル |
| `score_satisfaction_overall` | integer/null | 満足度スコア（存在する場合） |

- **レスポンス例**
```json
[
  {
    "comment_text": "Great session!",
    "llm_category": "その他",
    "llm_sentiment": "neutral",
    "llm_summary": "Great session!",
    "llm_importance_level": "low",
    "llm_importance_score": 0.0,
    "llm_risk_level": "none",
    "score_satisfaction_overall": null
  }
]
```

- **エラー**: 特別なハンドリングなし（条件に一致しない場合は空配列）

---

## 4. 今後の拡張メモ
- 認証方式（APIキー / OAuth 等）を導入する場合は共通ヘッダー仕様を追加する。  
- `POST /api/v1/uploads` を非同期化する場合、ジョブIDやポーリング手順を追記する。  
- `comment` テーブルに新たな属性を追加した際は `CommentAnalysisSchema` と本書を更新する。
