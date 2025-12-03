import base64
import json
import os
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, debug: bool = False):
        super().__init__(app)
        self.debug = debug

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 1. AWS ALB Authentication Headers
        oidc_identity = request.headers.get("x-amzn-oidc-identity")
        oidc_data = request.headers.get("x-amzn-oidc-data")

        user_info = {}

        if oidc_identity:
            # Production / ALB Environment
            user_info["sub"] = oidc_identity
            if oidc_data:
                try:
                    # JWT payload is the second part
                    payload_part = oidc_data.split(".")[1]
                    # Add padding if needed
                    payload_part += "=" * (-len(payload_part) % 4)
                    decoded = base64.urlsafe_b64decode(payload_part)
                    jwt_payload = json.loads(decoded)
                    user_info["email"] = jwt_payload.get("email")
                    user_info["username"] = jwt_payload.get("username") or jwt_payload.get("cognito:username")
                except Exception as e:
                    print(f"Failed to decode OIDC data: {e}")
        elif self.debug:
            # Local Development Mock
            user_info = {
                "sub": "local-dev-user-id",
                "username": "local_dev_user",
                "email": "dev@example.com",
                "role": "admin"
            }

        # Store in request state
        request.state.user = user_info

        response = await call_next(request)
        return response
