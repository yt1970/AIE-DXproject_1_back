from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AttributeItem(BaseModel):
    key: str
    label: str


class AttributesResponse(BaseModel):
    attributes: List[AttributeItem]


@router.get("/attributes", response_model=AttributesResponse)
def get_attributes():
    """
    利用可能な受講生属性の一覧を取得する。
    """
    return AttributesResponse(
        attributes=[
            {"key": "all", "label": "全体"},
            {"key": "student", "label": "学生"},
            {"key": "corporate", "label": "会員企業"},
            {"key": "invited", "label": "招待枠"},
            {"key": "faculty", "label": "教員"},
            {"key": "other", "label": "その他/不明"},
        ]
    )
