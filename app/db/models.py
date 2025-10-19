from sqlalchemy import (
    TIMESTAMP,
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Student(Base):
    __tablename__ = "student"

    # PK: 受講生ID
    student_id = Column(String(100), primary_key=True, nullable=False)
    # UNIQUE: メールアドレス
    email_address = Column(String(255), unique=True, nullable=False)
    account_id = Column(String(100))
    corporate_name = Column(String(255))
    school_name = Column(String(255))
    created_at = Column(TIMESTAMP, nullable=False)

    # リレーション定義 (Commentテーブルへの参照)
    comments = relationship("Comment", back_populates="student")


class UploadedFile(Base):
    __tablename__ = "uploaded_file"

    # PK: サロゲートキー
    file_id = Column(Integer, primary_key=True, autoincrement=True)

    # 講義の複合識別子（複合ユニークキーで整合性を保証）
    course_name = Column(String(255), nullable=False)
    lecture_date = Column(Date, nullable=False)
    lecture_number = Column(Integer, nullable=False)

    # その他の属性
    status = Column(String(20), nullable=False)  # PENDING, COMPLETED, FAILED
    s3_key = Column(String(512))  # ExcelファイルのS3パス
    upload_timestamp = Column(TIMESTAMP, nullable=False)

    # 複合ユニーク制約の定義 (これで重複登録を防ぐ)
    __table_args__ = (
        UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_course_lecture_instance",
        ),
    )

    # リレーション定義
    comments = relationship("Comment", back_populates="uploaded_file")


class Comment(Base):
    __tablename__ = "comment"

    # PK: 単一レコードID
    id = Column(Integer, primary_key=True, autoincrement=True)

    # FK (外部キー): どのファイル、どの受講生かを参照
    file_id = Column(Integer, ForeignKey("uploaded_file.file_id"), nullable=False)
    student_id = Column(String(100), ForeignKey("student.student_id"), nullable=False)

    # 数値評価データ
    score_satisfaction_overall = Column(Integer)
    # 生の自由記述コメント（LLM処理前）
    comment_learned_raw = Column(Text)
    comment_improvements_raw = Column(Text)
    # LLM分析結果
    llm_category = Column(String(50))
    llm_sentiment = Column(String(20))
    llm_summary = Column(Text)
    llm_importance_level = Column(String(20))
    llm_importance_score = Column(Float)
    llm_risk_level = Column(String(20))
    processed_at = Column(TIMESTAMP)  # LLM処理完了日時

    # リレーションの定義
    uploaded_file = relationship("UploadedFile", back_populates="comments")
    student = relationship("Student", back_populates="comments")
