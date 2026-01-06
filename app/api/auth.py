from fastapi import APIRouter, Request
from pydantic import BaseModel
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.settings import get_settings


router = APIRouter()

COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
LOGOUT_REDIRECT_URI = os.getenv("LOGOUT_REDIRECT_URI")

ALB_AUTH_COOKIE_NAMES = [
    "AWSELBAuthSessionCookie",
    "AWSELBAuthSessionCookie-0",
    "AWSELBAuthSessionCookie-1",
    "AWSELBAuthSessionCookie-2",
    "AWSELBAuthSessionCookie-3",
]


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
    target_url = settings.frontend_url
    return RedirectResponse(url=target_url, status_code=302)


# ------------------------------------------------------------------
# ★ Logout Endpoint（prefix なし）
# ------------------------------------------------------------------

@router.get("/logout", tags=["Auth"])
def logout():
    params = {
        "client_id": COGNITO_CLIENT_ID,
        "logout_uri": LOGOUT_REDIRECT_URI,
    }
    cognito_logout_url = (
        f"https://{COGNITO_DOMAIN}/logout?{urlencode(params)}"
    )

    response = RedirectResponse(url=cognito_logout_url, status_code=302)

    for cookie_name in ALB_AUTH_COOKIE_NAMES:
        response.set_cookie(
            key=cookie_name,
            value="",
            max_age=0,
            expires=0,
            path="/",
            httponly=True,
            secure=True,
            samesite="lax",
        )

    return response
