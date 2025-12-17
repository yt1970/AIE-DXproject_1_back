from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class UserInfoResponse(BaseModel):
    sub: str | None
    username: str | None
    email: str | None
    role: str | None


@router.get("/me", response_model=UserInfoResponse)
def get_current_user(request: Request):
    """
    ALBが付与したヘッダー情報を基に、現在のユーザー情報を返す。
    """
    user = request.state.user
    return UserInfoResponse(
        sub=user.get("sub"),
        username=user.get("username"),
        email=user.get("email"),
        role=user.get("role"),
    )
