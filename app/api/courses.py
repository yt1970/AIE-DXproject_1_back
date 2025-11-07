from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db


router = APIRouter()


@router.get("/courses", response_model=List[str])
def list_course_names(db: Session = Depends(get_db)) -> List[str]:
    """
    既存の講座名一覧を返す（重複なし）。
    UIのドロップダウン表示用。
    """
    rows = (
        db.query(models.UploadedFile.course_name)
        .distinct()
        .order_by(models.UploadedFile.course_name.asc())
        .all()
    )
    return [row[0] for row in rows]


