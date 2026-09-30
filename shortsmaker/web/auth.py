"""접근 암호(액세스 코드).

서버가 인터넷/공용 와이파이에 열리면 누구나 API 를 호출해 Gemini 크레딧과 연결된 계정을 쓸 수 있으므로
기본적으로 암호 없이는 열리지 않는다.

- 환경 변수 SHORTSMAKER_ACCESS_CODE (또는 --access-code) 로 암호를 정한다.
- 로컬(127.0.0.1)에서만 열 때는 암호 없이도 된다.
- 로컬이 아닌 주소로 열면서 암호가 없으면, 무작위 암호를 만들어 시작 로그에 한 번 보여준다.
- 로그인하면 30일짜리 쿠키가 생긴다. API 클라이언트는 `Authorization: Bearer <암호>` 도 쓸 수 있다.
- 로그인 실패는 IP 당 5회/분으로 제한한다.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

STATIC = Path(__file__).parent / "static"
COOKIE = "ss_auth"
# 로그인 전에도 받아야 하는 것: 로그인 화면, 설치(PWA) 자산, 상태 확인
PUBLIC_PATHS = ("/login", "/manifest.webmanifest", "/sw.js", "/healthz", "/favicon.ico")
PUBLIC_PREFIXES = ("/icons/",)
MAX_FAILS_PER_MIN = 5


def is_local(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def resolve_access_code(host: str, code: str | None) -> tuple[str | None, bool]:
    """(사용할 암호, 새로 만들었는지). 로컬 전용이고 암호가 없으면 인증을 끈다."""
    if code:
        return code.strip(), False
    if is_local(host):
        return None, False
    return secrets.token_urlsafe(6), True


def _token(code: str, salt: str) -> str:
    return hmac.new(salt.encode(), code.encode(), hashlib.sha256).hexdigest()


def install_auth(app: FastAPI, access_code: str | None) -> None:
    if not access_code:
        return                                   # 로컬 전용: 인증 없음
    app.state.auth_enabled = True
    salt = secrets.token_hex(16)                 # 서버를 다시 시작하면 기존 쿠키는 무효 (다시 로그인)
    good = _token(access_code, salt)
    fails: dict[str, deque] = defaultdict(deque)

    def authed(request: Request) -> bool:
        cookie = request.cookies.get(COOKIE, "")
        if cookie and hmac.compare_digest(cookie.encode(), good.encode()):
            return True
        auth = request.headers.get("authorization", "")
        return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip().encode(), access_code.encode())

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES) or authed(request):
            return await call_next(request)
        if path.startswith("/api/") or path.startswith("/outputs/"):
            return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login")
    def login_page():
        return FileResponse(STATIC / "login.html")

    @app.post("/login")
    def login(request: Request, code: str = Form("")):
        ip = request.client.host if request.client else "?"
        now = time.time()
        q = fails[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= MAX_FAILS_PER_MIN:
            return JSONResponse({"detail": "시도가 너무 많습니다. 1분 뒤에 다시 해주세요."}, status_code=429)
        if not hmac.compare_digest(code.strip().encode(), access_code.encode()):
            q.append(now)
            return JSONResponse({"detail": "암호가 맞지 않습니다."}, status_code=401)
        resp = JSONResponse({"ok": True})
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        resp.set_cookie(COOKIE, good, max_age=30 * 86400, httponly=True, samesite="lax", secure=secure)
        return resp

    @app.post("/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp
