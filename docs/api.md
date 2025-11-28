# API エンドポイント

AIE-DXプロジェクトのRESTful APIエンドポイント一覧です。

## エンドポイント一覧

#### CSVファイルアップロード
```
POST /api/v1/uploads
```

CSVファイルとメタデータをアップロードし、データベースに保存します。

**リクエスト**:
- Content-Type: `multipart/form-data`
- Body:
  - `file`: CSV ファイル（required）
  - `academic_year`: 年度（required）
  - `term`: 学期（required）
  - `course_name`: 講義名（required）
  - `session`: セッション番号（required）
  - `lecture_date`: 講義実施日 YYYY-MM-DD（required）
  - `instructor_name`: 講師名（required）
  - `batch_type`: バッチ種別 'preliminary' or 'confirmed'（optional, デフォルト: 'preliminary'）
  - `zoom_participants`: Zoom参加者数（optional）
  - `recording_views`: 録画視聴回数（optional）

**レスポンス**: 
```json
{
  "upload_id": 123,
  "message": "Upload successful",
  "status": "processing"
}
```

#### アップロード状態確認
```
GET /api/v1/uploads/{upload_id}/status
```

アップロードの処理状態を確認します。

**レスポンス**:
```json
{
  "upload_id": 123,
  "status": "completed",
  "total_responses": 45,
  "total_comments": 120,
  "analyzed_comments": 120
}
```

---

### 講義・コース管理

#### 講義一覧取得
```
GET /api/v1/lectures
```

講義一覧を取得します（フィルタ・ページング対応）。

**クエリパラメータ**:
- `academic_year`: 年度でフィルタ（optional）
- `term`: 学期でフィルタ（optional）
- `instructor_name`: 講師名でフィルタ（optional）
- `page`: ページ番号（optional, デフォルト: 1）
- `page_size`: ページサイズ（optional, デフォルト: 20）

**レスポンス**:
```json
{
  "lectures": [
    {
      "id": 1,
      "academic_year": 2024,
      "term": "前期",
      "name": "データサイエンス入門",
      "session": "第1回",
      "lecture_on": "2024-04-10",
      "instructor_name": "山田太郎",
      "description": "..."
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 20
}
```

#### 講義詳細取得
```
GET /api/v1/lectures/{lecture_id}
```

特定の講義の詳細情報を取得します。

**レスポンス**:
```json
{
  "id": 1,
  "academic_year": 2024,
  "term": "前期",
  "name": "データサイエンス入門",
  "session": "第1回",
  "lecture_on": "2024-04-10",
  "instructor_name": "山田太郎",
  "description": "...",
  "survey_batches": [
    {
      "id": 123,
      "batch_type": "preliminary",
      "uploaded_at": "2024-04-11T10:30:00"
    }
  ]
}
```

#### コース一覧取得
```
GET /api/v1/courses
```

コース（講義名）の一覧を取得します。

**レスポンス**:
```json
{
  "courses": [
    {
      "name": "データサイエンス入門",
      "lecture_count": 15,
      "latest_lecture_date": "2024-07-20"
    }
  ]
}
```

---

### データ取得

#### コメント一覧取得
```
GET /api/v1/comments
```

コメント一覧を取得します（フィルタ対応）。

**クエリパラメータ**:
- `survey_batch_id`: バッチIDでフィルタ（optional）
- `sentiment_type`: 感情タイプでフィルタ（optional, 値: positive/neutral/negative）
- `category`: カテゴリでフィルタ（optional, 値: instructor/operation/material/content/other）
- `importance_level`: 重要度でフィルタ（optional, 値: high/medium/low）
- `is_abusive`: 不適切フラグでフィルタ（optional, 値: true/false）
- `page`: ページ番号（optional, デフォルト: 1）
- `page_size`: ページサイズ（optional, デフォルト: 50）

**レスポンス**:
```json
{
  "comments": [
    {
      "id": 1,
      "response_id": 10,
      "question_type": "good_point",
      "comment_text": "説明がわかりやすかった",
      "llm_sentiment_type": "positive",
      "llm_category": "instructor",
      "llm_importance_level": "medium",
      "llm_is_abusive": false,
      "is_analyzed": true
    }
  ],
  "total": 500,
  "page": 1,
  "page_size": 50
}
```

#### メトリクス集計データ取得
```
GET /api/v1/metrics
```

メトリクス集計データを取得します。

**クエリパラメータ**:
- `survey_batch_id`: バッチID（required）
- `student_attribute`: 学生属性でフィルタ（optional）

**レスポンス**:
```json
{
  "survey_batch_id": 123,
  "summaries": [
    {
      "student_attribute": "学部生",
      "response_count": 30,
      "nps": 45.67,
      "promoter_count": 20,
      "passive_count": 5,
      "detractor_count": 5,
      "avg_satisfaction_overall": 8.5
    }
  ],
  "score_distributions": [
    {
      "student_attribute": "学部生",
      "question_key": "satisfaction_overall",
      "distribution": {
        "10": 15,
        "9": 5,
        "8": 3,
        "7": 2
      }
    }
  ],
  "comment_summaries": [
    {
      "student_attribute": "学部生",
      "analysis_type": "sentiment",
      "summary": {
        "positive": 80,
        "neutral": 30,
        "negative": 10
      }
    }
  ]
}
```

#### ダッシュボードデータ取得
```
GET /api/v1/dashboard
```

ダッシュボード用の統合データを取得します。

**クエリパラメータ**:
- `lecture_id`: 講義ID（optional）
- `academic_year`: 年度（optional）
- `term`: 学期（optional）

**レスポンス**:
```json
{
  "overview": {
    "total_lectures": 50,
    "total_responses": 1500,
    "average_nps": 52.3,
    "average_satisfaction": 8.2
  },
  "recent_lectures": [...],
  "top_comments": [...]
}
```

---

### 分析

#### コメント分析トリガー
```
POST /api/v1/analysis/comments
```

指定したバッチのコメントをLLM分析します（通常は自動実行されますが、手動トリガーも可能）。

**リクエスト**:
```json
{
  "survey_batch_id": 123,
  "force_reanalyze": false
}
```

**レスポンス**:
```json
{
  "message": "Analysis started",
  "survey_batch_id": 123,
  "task_id": "abc-123-def"
}
```

---

## エラーレスポンス

全てのエンドポイントは以下の形式でエラーを返します：

```json
{
  "detail": "エラーメッセージ"
}
```

**HTTPステータスコード**:
- `200 OK`: 成功
- `201 Created`: 作成成功
- `400 Bad Request`: リクエストが不正
- `404 Not Found`: リソースが見つからない
- `409 Conflict`: 重複エラー
- `422 Unprocessable Entity`: バリデーションエラー
- `500 Internal Server Error`: サーバーエラー

## 認証

現在のバージョンでは認証は実装されていません。将来的にはJWT認証またはAPIキー認証を実装予定です。

## レート制限

現在のバージョンではレート制限は実装されていません。本番環境ではNginxやAPI Gatewayでのレート制限を推奨します。
