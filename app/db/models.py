import enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    ForeignKey, TIMESTAMP, Enum as SAEnum, UniqueConstraint,
    Float, Date
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func  # サーバーサイドのデフォルト日時を設定するため

Base = declarative_base()

# --- 1. マスターテーブル (生徒) ---
class Student(Base):
    """
    生徒マスターテーブル (Students)
    全講義を横断して一意となる生徒の「変わらない」情報を格納します。
    """
    __tablename__ = "students"

    # PK: アカウントID (入力データから)
    account_id = Column(String(255), primary_key=True)

    # 講義DBから引用したカラム
    student_id_alias = Column(String(255), index=True) # 受講生ID (アカウントIDと別の場合)
    account_name = Column(String(255)) # アカウント名
    role = Column(String(100)) # ロール
    school_name = Column(String(255)) # 学校名
    faculty = Column(String(255)) # 学部
    company_name = Column(String(255)) # 企業名
    department = Column(String(255)) # 部署名

    # リレーション: 一人の生徒は複数の講義に登録(Enroll)できる
    enrollments = relationship("Enrollment", back_populates="student")

# --- 2. マスターテーブル (講義) ---
class Lecture(Base):
    """
    講義マスターテーブル (Lectures)
    開催される講義の情報を格納します。
    """
    __tablename__ = "lectures"

    # PK: システムが採番するID
    lecture_id = Column(Integer, primary_key=True, autoincrement=True)

    lecture_name = Column(String(255), nullable=False) # 講義名
    lecture_year = Column(Integer, nullable=False) # 講義開催年

    # リレーション: 一つの講義には複数の生徒が登録(Enroll)される
    enrollments = relationship("Enrollment", back_populates="lecture")

    # 制約: 講義名と開催年の組み合わせはユニークでなければならない
    __table_args__ = (
        UniqueConstraint("lecture_name", "lecture_year", name="uq_lecture_name_year"),
    )

# --- 3. 中間テーブル (受講登録) ---
class Enrollment(Base):
    """
    受講登録テーブル (Enrollments)
    「どの生徒が」「どの講義に」登録したかを管理する、多対多の中間テーブル。
    """
    __tablename__ = "enrollments"

    # PK: システムが採番するID
    enrollment_id = Column(Integer, primary_key=True, autoincrement=True)

    # FK: 外部キー
    student_id = Column(String(255), ForeignKey("students.account_id"), nullable=False, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.lecture_id"), nullable=False, index=True)

    # 講義DBから引用したカラム
    application_type = Column(String(100)) # 申込区分
    application_type_jp = Column(String(100)) # 申込区分（日本語）

    # リレーション:
    student = relationship("Student", back_populates="enrollments")
    lecture = relationship("Lecture", back_populates="enrollments")

    # リレーション: 1回の受講登録に対し、複数回の評価(Submission)があり得る（例: 毎週アンケート）
    submissions = relationship("Submission", back_populates="enrollment")

    # 制約: 一人の生徒は同じ講義に一度しか登録できない
    __table_args__ = (
        UniqueConstraint("student_id", "lecture_id", name="uq_student_lecture"),
    )

# --- 4. データテーブル (数値評価) ---
class Submission(Base):
    """
    評価送信テーブル (Submissions)
    1回のアンケート回答（数値・真偽値）を格納します。
    """
    __tablename__ = "submissions"

    submission_id = Column(Integer, primary_key=True, autoincrement=True) # PK

    # FK: どの受講登録(Enrollment)に対する回答か
    enrollment_id = Column(Integer, ForeignKey("enrollments.enrollment_id"), nullable=False, index=True)

    submitted_at = Column(TIMESTAMP, server_default=func.now()) # 回答日時

    # --- ここに数値評価・真偽値カラムをすべて列挙 ---
    satisfaction_overall = Column(Integer) # 本日の 総合的な満足度
    workload_appropriate = Column(Integer) # 学習量は適切だった
    content_understood = Column(Integer) # 講義内容が十分に理解できた
    admin_support_good = Column(Integer) # 運営側のアナウンスが適切だった
    instructor_overall = Column(Integer) # 本日の 講師の総合的な満足度
    instructor_time_efficient = Column(Integer) # 授業時間を効率的に使っていた
    instructor_q_and_a = Column(Integer) # 質問に丁寧に対応してくれた
    instructor_voice = Column(Integer) # 話し方や声の大きさが適切だった
    self_prepared = Column(Integer) # 事前に予習をした
    self_motivated = Column(Integer) # 意欲をもって講義に臨んだ
    self_application = Column(Integer) # 今回学んだことを学習や研究に生かせる
    nps_recommend = Column(Integer) # 親しいご友人にこの講義の受講をお薦めしますか？

    # リレーション:
    enrollment = relationship("Enrollment", back_populates="submissions")

    # リレーション: 1回の回答(Submission)には複数の自由記述(Comment)が含まれる
    comments = relationship("Comment", back_populates="submission", cascade="all, delete-orphan")

# --- 5. データテーブル (自由記述コメント) ---

# Python側でEnumを定義（DBのEnumと連動）
class CommentType(enum.Enum):
    learned = "learned"               # 【必須】本日の講義で学んだこと
    good_point = "good_point"         # （任意）特によかった部分
    improvement_point = "improvement_point" # （任意）分かりにくかった部分や改善点
    instructor_feedback = "instructor_feedback" # （任意）講師について
    future_request = "future_request"   # （任意）今後開講してほしい講義
    free_text = "free_text"             # （任意）ご自由にご意見を

class Comment(Base):
    """
    コメントテーブル (Comments)
    自由記述コメントを「縦持ち」で格納します。
    """
    __tablename__ = "comments"

    comment_id = Column(Integer, primary_key=True, autoincrement=True) # PK

    # FK: どの回答(Submission)に紐づくか
    submission_id = Column(Integer, ForeignKey("submissions.submission_id"), nullable=False, index=True)

    # どの種類のコメントか
    comment_type = Column(SAEnum(CommentType), nullable=False)

    # コメント本文
    comment_text = Column(Text, nullable=False)

    # リレーション:
    submission = relationship("Submission", back_populates="comments")

    # リレーション: 1つのコメントに1つの分析結果が紐づく (1-to-1)
    analysis = relationship("CommentAnalysis", back_populates="comment", uselist=False, cascade="all, delete-orphan")

# --- 6. 分析結果テーブル ---

# Python側でEnumを定義
class SentimentType(enum.Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"

class CommentAnalysis(Base):
    """
    コメント分析テーブル (CommentAnalyses)
    LLMなどによる分析結果を格納します。（元のCommentIdテーブルの役割）
    """
    __tablename__ = "comment_analyses"

    analysis_id = Column(Integer, primary_key=True, autoincrement=True) # PK

    # FK: どのコメント(Comment)に対する分析か (1-to-1にするため unique=True)
    comment_id = Column(Integer, ForeignKey("comments.comment_id"), nullable=False, unique=True)

    # --- 分析結果 ---
    is_improvement_needed = Column(Boolean, nullable=False, default=False) # 改善が必要か (kaizen_label)
    is_slanderous = Column(Boolean, nullable=False, default=False) # 誹謗中傷か (denger_comment)
    sentiment = Column(SAEnum(SentimentType)) # ポジネガ

    # (任意) ご提示のコードにあった項目も追加可能
    # llm_summary = Column(Text) # 要約
    # llm_importance_score = Column(Float) # 重要度

    analysis_version = Column(String(50)) # 分析ロジックのバージョン管理用
    analyzed_at = Column(TIMESTAMP, server_default=func.now()) # 分析実行日時

    # リレーション (1-to-1)
    comment = relationship("Comment", back_populates="analysis")

# --- 7. 非同期処理管理テーブル ---
class AnalysisJob(Base):
    """
    非同期分析ジョブ管理テーブル (AnalysisJobs)
    ファイルアップロードごとの処理（ジョブ）の状態を管理します。
    将来的に分析処理を非同期化した場合、クライアントはこのテーブルの情報を
    ステータス確認API経由でポーリングし、進捗を確認します。
    """
    __tablename__ = "analysis_jobs"

    # PK: ジョブを一意に識別するID
    job_id = Column(Integer, primary_key=True, autoincrement=True)
    # FK: どの講義に紐づくジョブか
    lecture_id = Column(Integer, ForeignKey("lectures.lecture_id"), nullable=False, index=True)

    # ジョブの現在の状態 (例: PENDING, PROCESSING, COMPLETED, FAILED)
    status = Column(String(50), nullable=False, default="PENDING")
    original_filename = Column(String(255)) # アップロードされた元のファイル名
    total_submissions = Column(Integer, default=0) # 処理対象の総行数
    processed_submissions = Column(Integer, default=0) # 処理済みの行数
    error_message = Column(Text) # エラー発生時のメッセージ
    created_at = Column(TIMESTAMP, server_default=func.now()) # ジョブ作成日時
    completed_at = Column(TIMESTAMP, nullable=True) # ジョブ完了日時

    lecture = relationship("Lecture")

# --- 8. 設定テーブル (カラムマッピング) ---
class MappingType(enum.Enum):
    """マッピングの種類を定義するEnum"""
    COMMENT = "COMMENT"
    SCORE = "SCORE"

class ColumnMapping(Base):
    """
    CSVヘッダーとDBカラムのマッピングを管理するテーブル。
    これにより、CSVのフォーマット変更にコード修正なしで対応できるようになります。
    """
    __tablename__ = "column_mappings"

    mapping_id = Column(Integer, primary_key=True, autoincrement=True)
    # CSVファイル上のヘッダー名 (例: "【必須】本日の講義で学んだこと")
    csv_header = Column(String(255), nullable=False, unique=True)
    # マッピングの種類 (COMMENT or SCORE)
    mapping_type = Column(SAEnum(MappingType), nullable=False)
    # DB上の対応先 (例: "learned" や "satisfaction_overall")
    db_column_name = Column(String(255), nullable=False)

    is_active = Column(Boolean, default=True, nullable=False) # このマッピングが有効か