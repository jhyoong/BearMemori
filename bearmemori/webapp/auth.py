import hashlib
import hmac

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware


class WebappAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self._secret = secret
        self._token = hashlib.sha256(secret.encode()).hexdigest()

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/webapp"):
            return await call_next(request)

        # Allow login page and static files
        if request.url.path in ("/webapp/login",) or request.url.path.startswith("/webapp/static"):
            return await call_next(request)

        # Check session cookie
        session_token = request.cookies.get("webapp_session")
        if not session_token or not hmac.compare_digest(session_token, self._token):
            return RedirectResponse(url="/webapp/login", status_code=302)

        return await call_next(request)

    def create_session_cookie(self, response: Response) -> Response:
        response.set_cookie(
            key="webapp_session",
            value=self._token,
            httponly=True,
            samesite="strict",
            max_age=60 * 60 * 24 * 30,  # 30 days
        )
        return response

    def verify_secret(self, provided: str) -> bool:
        return hmac.compare_digest(hashlib.sha256(provided.encode()).hexdigest(), self._token)
