# API エンドポイント

AIE-DX プロジェクトの FastAPI 実装で現在提供している REST API 一覧です。  
ルーター構成: Upload / Analysis / Results(Comments) / Courses / Lectures / Metrics / Dashboard。  
本書は現行実装を基準に記載しており、モデルとの不整合などでエンドポイントが失敗する場合はその旨を各節で説明しています。

---

## 0. システム

### 0-1. ヘルスチェック
```
GET /health
```
FastAPI アプリの稼働確認。DB やワーカーの状態はまだチェックしていません。

**レスポンス**
```json
{
  "status": "ok",
  "timestamp": "2025-01-01T12:00:00.000000",
  "app_name": "AIE-DX Backend",
  "environment": "local"
}
```

---

## 1. アップロード & 分析

### 1-1. CSV アップロード
```
POST /api/v1/uploads
```
LLM 分析対象の CSV を受け取り、ストレージ保存と解析ジョブ投入を行います。

- Content-Type: `multipart/form-data`
- Body
  - `file` (required): CSV ファイル
  - `metadata` (required): JSON 文字列。現行実装で認識しているフィールドは以下のみです（それ以外は無視されます）。
    | フィールド | 型 | 必須 | 備考 |
    | --- | --- | --- | --- |
    | `course_name` | string | Yes | `Lecture.name` に保存。 |
    | `lecture_on` | date | Yes | `YYYY-MM-DD`。年度はこの日付から 4 月起算で算出。 |
    | `lecture_number` | int | Yes | `Lecture.session` に文字列として保存。 |
    | `lecture_id` | int | No | 既存講義へ直接紐付けたい場合のみ。 |
    | `uploader_id` | int | No | リクエストでは受け付けるが DB には保存されず無視される。 |
    ```json
    {
      "course_name": "データサイエンス入門",
      "lecture_on": "2024-04-10",
      "lecture_number": 1,
      "lecture_id": null,
      "uploader_id": 999
    }
    ```
    - `lecture_id` が無い場合は `course_name / lecture_on / lecture_number` で既存講義を検索し、無ければ `term="Unknown"`, `instructor_name="TBD"` などの初期値で自動作成されます。

**レスポンス**
```json
{
  "survey_batch_id": 123,
  "status_url": "/api/v1/uploads/123/status",
  "message": "Upload accepted. Analysis will run in the background."
}
```

### 1-2. 重複チェック
```
GET /api/v1/uploads/check-duplicate
```
同じ講義（講座名/日付/回）で既にアップロード済みかを判定します。

| クエリ | 型 | 必須 | 備考 |
| --- | --- | --- | --- |
| `course_name` | string | Yes | 講義名 |
| `lecture_on` | date | Yes | `YYYY-MM-DD` |
| `lecture_number` | int | Yes | 回数 |

`Lecture` が見つかった場合でも、紐づく `SurveyBatch` のうち最初の 1 件だけを確認して返却する実装になっており、複数バッチの存在は考慮していません。

**レスポンス**
```json
{
  "exists": true,
  "survey_batch_id": 123
}
```

### 1-3. アップロード削除
```
DELETE /api/v1/uploads/{survey_batch_id}
```
対象バッチに紐づく回答・コメント・集計結果を削除します。サマリがまだ無い (=処理中) 場合は `409 Conflict`。

「処理中」判定には `SurveySummary` の有無のみを利用しており、ジョブキューやバックグラウンドタスクの状態は参照しません。

**レスポンス**
```json
{
  "survey_batch_id": 123,
  "deleted": true,
  "removed_comments": 80,
  "removed_survey_responses": 40
}
```

### 1-4. 識別情報でアップロード削除
```
DELETE /api/v1/uploads/by-identity
```
ボディで講義条件を指定して単一バッチを削除します。`analysis_version` を指定すると特定バージョンのコメント/サマリだけを削除可能。

実装では `course_name` と `lecture_number`（必要に応じて `academic_year`, `period`）で `Lecture` を 1 件に絞り、その講義に紐づく最初の `SurveyBatch` のみが削除対象になります。複数バッチの選択には対応していません。

**リクエスト**
```json
{
  "course_name": "データサイエンス入門",
  "academic_year": "2024",
  "period": "前期",
  "lecture_number": 1,
  "analysis_version": "preliminary"
}
```

**レスポンス**は `DELETE /uploads/{id}` と同じ。

### 1-5. 速報 → 確定
```
POST /api/v1/uploads/{survey_batch_id}/finalize
```
`batch_type` を `confirmed` に更新し、関連コメントの `analysis_version` を `final` に置き換えたうえで再集計します。

`SurveyBatch.finalized_at` 列は存在しないため、確定化は `batch_type` を `confirmed` に更新し、`final` バージョンの `SurveySummary / CommentSummary / ScoreDistribution` を再生成する形で行われます。

**レスポンス**
```json
{
  "survey_batch_id": 123,
  "finalized": true,
  "updated_comments": 75
}
```

### 1-6. ステータス確認
```
GET /api/v1/uploads/{survey_batch_id}/status
```
解析状況と処理済みコメント数を返します。`SurveySummary` が存在すれば `COMPLETED`、無ければ `PROCESSING` 判定となります。

**レスポンス**
```json
{
  "survey_batch_id": 123,
  "status": "COMPLETED",
  "total_comments": 0,
  "processed_count": 0,
  "task_id": null,
  "queued_at": "2024-04-11T10:30:00Z",
  "processing_started_at": null,
  "processing_completed_at": null,
  "error_message": null
}
```
`ResponseComment` テーブルに `survey_batch_id` 列が無いため、`processed_count` を算出しようとした時点で例外が発生し、現状は 500 エラーになります。実際の処理状況を確認する場合は `SurveySummary` のレコード有無を直接確認する必要があります。

---

## 2. コメント結果

### 2-1. コース別コメント一覧
```
GET /api/v1/courses/{course_name}/comments
```
最新のコメント分析結果を取得。`ResponseComment` に紐づくスコアを計算済みフィールドで返します。

| クエリ | デフォルト | 説明 |
| --- | --- | --- |
| `limit` | 100 | 取得件数 |
| `skip` | 0 | オフセット |
| `version` | null | `preliminary` / `final` のいずれか（バリデーションはしていません） |
ページングは `limit` と `skip` のみで総件数は返さず、指定した `course_name` に紐づくすべての講義・バッチを JOIN して取得します。

**レスポンス（一部）**
```json
[
  {
    "question_type": "good_point",
    "comment_text": "説明がわかりやすかった",
    "llm_category": "instructor",
    "llm_sentiment_type": "positive",
    "llm_importance_level": "medium",
    "llm_is_abusive": false,
    "is_analyzed": true,
    "score_satisfaction_overall": 9,
    "score_satisfaction_content_understanding": 8,
    "score_satisfaction_instructor_overall": 10
  }
]
```

---

## 3. 講義・コース管理

現状の SQLAlchemy モデルは `Lecture.name` / `Lecture.term` を持つ一方で、Lectures API は存在しない `course_name` / `period` 列を参照しており、実行すると AttributeError になります。以下のエンドポイントは修正が入るまで利用できません。
同様に `Courses` ルーターも `Lecture.category` 列の存在を前提としており、`category` クエリパラメータを指定すると即座に 500 エラーになります（列が存在しないため）。`category` パラメータは現状使用しないでください。

### 3-1. 講義一覧
```
GET /api/v1/lectures
```
フィルタ＆ソートのみを提供（ページングなし）。レスポンスは `LectureSummaryResponse` の配列。

| クエリ | 型 | 説明 |
| --- | --- | --- |
| `name` | string | 講義名部分一致 |
| `year` | int | 学年 |
| `period` | string | 期間（前期/後期など） |
| `sort_by` | string | `course_name`(default) / `academic_year` / `period` |
| `sort_order` | string | `asc`(default) / `desc` |

**レスポンス例**
```json
[
  {
    "id": 1,
    "course_name": "データサイエンス入門",
    "academic_year": "2024",
    "period": "前期",
    "term": "前期",
    "name": "データサイエンス入門",
    "session": "1",
    "instructor_name": "山田太郎",
    "lecture_on": "2024-04-10"
  }
]
```

### 3-2. メタデータ取得
```
GET /api/v1/lectures/metadata
```
フォーム向けの候補値を返します。
```json
{
  "courses": ["データサイエンス入門", "..."],
  "years": [2023, 2024],
  "terms": ["前期", "後期"]
}
```

### 3-3. 講義作成
```
POST /api/v1/lectures
```
Body (`application/json`)
```json
{
  "course_name": "AI基礎",
  "academic_year": 2024,
  "period": "前期",
  "category": "講義内容"
}
```
重複条件: `course_name` + `academic_year` + `period`。
レスポンスは `LectureSummaryResponse`。

### 3-4. 講義更新
```
PUT /api/v1/lectures/{lecture_id}
```
部分更新可能。重複チェックは更新後の値で実施。レスポンスは `LectureSummaryResponse`。

### 3-5. 講義削除
```
DELETE /api/v1/lectures/{lecture_id}
```
関連する SurveyBatch / SurveyResponse / ResponseComment / Summary をまとめて削除。処理中バッチ（status=`PROCESSING`）があると 409。

モデルに `SurveyBatch.status` と `ResponseComment.survey_batch_id` が存在しないため、現行コードは削除処理の途中で例外を発生させます。利用前に DB スキーマの修整が必要です。

**レスポンス**
```json
{
  "lecture_id": 1,
  "deleted": true,
  "removed_batches": 2,
  "removed_comments": 160,
  "removed_survey_responses": 80
}
```

### 3-6. 講義詳細
```
GET /api/v1/lectures/{lecture_id}
```
`score_distributions` を含む詳細を返しますが、`Lecture` モデルに `course_name` フィールドが無いため現在は常に 500 エラーになります。
```json
{
  "id": 1,
  "course_name": "データサイエンス入門",
  "academic_year": "2024",
  "period": "前期",
  "term": "前期",
  "name": "データサイエンス入門",
  "session": "1",
  "instructor_name": "山田太郎",
  "lecture_on": "2024-04-10",
  "description": "Auto-created from upload",
  "score_distributions": [
    {
      "question_key": "score_overall_satisfaction",
      "score_value": 10,
      "count": 15,
      "student_attribute": "ALL"
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

### 3-7. コース一覧（名称・年度・期間）
```
GET /api/v1/courses
```
クエリは `name / year / period / sort_by / sort_order`（講義一覧と同じ）に加えて `category` が実装上は受け付けられますが、前述の通り `Lecture.category` 列が存在しないため `category` を指定すると 500 エラーになります。  
レスポンスは `LectureInfo` の配列:
`lectures` テーブルの各レコードがそのまま返るため、同じ講義でも回数違いで重複が発生し、`Lecture.name` が `course_name` として返却されます。
```json
[
  {
    "course_name": "データサイエンス入門",
    "academic_year": "2024",
    "period": "前期"
  }
]
```

---

## 4. メトリクス入力

### 4-1. バッチ単位で取得
```
GET /api/v1/uploads/{survey_batch_id}/metrics
```
### 4-2. バッチ単位で更新
```
PUT /api/v1/uploads/{survey_batch_id}/metrics
```
Body (`LectureMetricsPayload`)
```json
{
  "zoom_participants": 120,
  "recording_views": 450
}
```
レスポンス (`LectureMetricsResponse`)
```json
{
  "survey_batch_id": 123,
  "zoom_participants": 120,
  "recording_views": 450,
  "updated_at": "2024-04-12T09:00:00Z"
}
```
`updated_at` は GET 時に `SurveyBatch.uploaded_at`、PUT 時に `datetime.now()` を返すだけで、専用の更新日時列はまだありません。

### 4-3. 講義単位で取得/更新
```
GET /api/v1/lectures/{lecture_id}/metrics
PUT /api/v1/lectures/{lecture_id}/metrics
```
講義に紐づく「代表バッチ」（優先順: confirmed 最新 → preliminary 最新）を自動選択して同じレスポンス形式で返します。更新時も代表バッチの値を上書きします。
GET でバッチが 1 件も無い場合は `survey_batch_id: 0` のレスポンスだけが返り、PUT はバッチ未登録時に `400` を返します。代表バッチの選択は `_choose_target_batch_for_lecture` で `batch_type` と `uploaded_at` を見る単純な実装です。

---

## 5. ダッシュボード

Dashboard ルーターは `SurveyBatch.finalized_at`, `SurveyBatch.lecture_number`, `SurveySummary.score_overall_satisfaction` など現行スキーマに無い列を参照するため、`/dashboard/...` 系エンドポイントはすべて 500 エラーになります。以下は想定仕様ですが、レスポンスは返ってきません。

### 5-1. 講義全体サマリ
```
GET /api/v1/dashboard/{lecture_id}/overview
```
| クエリ | 既定 | 説明 |
| --- | --- | --- |
| `version` | `final` | `final` / `preliminary` |

**レスポンス（一部）**
```json
{
  "scores": {
    "overall_satisfaction": 8.5,
    "content_volume": 7.8,
    "...": null
  },
  "nps": {
    "score": 52.3,
    "promoters": 40,
    "passives": 10,
    "detractors": 5,
    "total": 55
  },
  "counts": {
    "responses": 120,
    "comments": 80,
    "important_comments": 35
  },
  "sentiments": {
    "positive": 60,
    "neutral": 15,
    "negative": 5
  },
  "categories": {
    "lecture_content": 30,
    "lecture_material": 20,
    "operations": 10,
    "other": 5
  },
  "timeline": [
    {
      "lecture_number": 1,
      "batch_id": 2001,
      "nps": 55.0,
      "response_count": 40,
      "avg_overall_satisfaction": 8.6
    }
  ]
}
```

### 5-2. 講義番号ごとの詳細
```
GET /api/v1/dashboard/{lecture_id}/per_lecture
```
`version` クエリは overview と同じ。  
レスポンス
```json
{
  "lectures": [
    {
      "lecture_number": 1,
      "batch_id": 2001,
      "scores": { "...": 8.3 },
      "nps": { "score": 50.0, "promoters": 18, "passives": 4, "detractors": 2, "total": 24 },
      "sentiments": { "positive": 20, "neutral": 5, "negative": 2 },
      "categories": { "lecture_content": 8, "...": 1 },
      "importance": {
        "low": 5,
        "medium": 10,
        "high": 7,
        "important_comments": 17
      },
      "counts": {
        "responses": 40,
        "comments": 22,
        "important_comments": 17
      }
    }
  ]
}
```

---

## 6. エラー形式

全エンドポイントは FastAPI デフォルトの JSON エラーを返します。
```json
{
  "detail": "エラーメッセージ"
}
```

代表的な HTTP ステータス:
- `200 OK`: 成功
- `201 Created`: リソース作成
- `400 Bad Request`: パラメータ不正
- `404 Not Found`: リソース未存在
- `409 Conflict`: 重複 or 処理中
- `422 Unprocessable Entity`: バリデーション失敗
- `500 Internal Server Error`: サーバーエラー