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


from app.core.settings import get_settings
from fastapi.responses import RedirectResponse

@router.get("/login", summary="Login Redirect")
def login_redirect():
    """
    ALB認証フローの起着点。
    既にALBで認証されているため、フロントエンドのダッシュボードへリダイレクトする。
    """
    settings = get_settings()
    # 末尾のスラッシュ調整などは必要に応じて行うが、基本は設定値を信頼
    target_url = f"{settings.frontend_url}/dashboard"
    return RedirectResponse(url=target_url, status_code=302)
