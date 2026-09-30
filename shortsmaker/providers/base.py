"""Provider 공통 기반: 키 관리(서버 전용, 로그 마스킹), 상태 기록, 사용량."""
from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


class ProviderError(RuntimeError):
    def __init__(self, message: str = "", status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        """결제(402)/인증(401,403)/모델 없음(404) 은 다시 해도 같으므로 재시도하지 않는다."""
        return self.status not in (401, 402, 403, 404)


class NotConfigured(ProviderError):
    pass


def mask(secret: str | None) -> str:
    if not secret:
        return "(none)"
    return secret[:3] + "…" + secret[-2:] if len(secret) > 8 else "***"


_KEY_LIKE = re.compile(r"(sk-[A-Za-z0-9_-]{6,}|AIza[0-9A-Za-z_-]{10,}|gsk_[A-Za-z0-9]{6,}|Bearer\s+\S+|key=[^&\s]+)")


def scrub(text: str) -> str:
    """에러 메시지/로그에서 키처럼 보이는 문자열을 가린다."""
    return _KEY_LIKE.sub(lambda m: mask(m.group(0)), str(text))


@dataclass
class Usage:
    input_units: float = 0      # 토큰 또는 글자 수
    output_units: float = 0
    estimated_cost: float = 0.0


@dataclass
class ProviderResult:
    value: Any
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency: float = 0.0


def image_b64(path: str | Path) -> tuple[str, str]:
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return base64.b64encode(p.read_bytes()).decode(), mime


def parse_json(text: str) -> Any:
    """모델 출력에서 JSON 부분만 안전하게 파싱."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not m:
            raise ProviderError("모델 응답이 JSON 이 아닙니다")
        return json.loads(m.group(1))


class Provider:
    """모든 외부 API 는 이 클래스를 통해서만 호출한다 (키는 서버 환경변수에서만 읽음)."""

    name = "base"
    env_key: str | None = None
    tasks: tuple[str, ...] = ()
    # 유료 생성 API 는 health check 로 호출하지 않는다
    paid_generation = False
    # 환경 '자격 증명(API credentials)'으로 프록시가 키를 대신 붙여주는 경우를 감지하기 위한 무료 조회 URL
    probe_url: str | None = None

    def __init__(self, session: requests.Session | None = None, api_key: str | None = None):
        self.http = session or requests.Session()
        self._key = api_key if api_key is not None else (os.environ.get(self.env_key) if self.env_key else None)
        self._proxied: bool | None = None

    def _probe_proxy_credential(self) -> bool:
        """키 없이 무료 엔드포인트를 호출해서 프록시가 자격 증명을 붙여주는지 확인 (결과 캐시)."""
        if self._proxied is None:
            self._proxied = False
            if self.probe_url and os.environ.get("SHORTSMAKER_PROBE_CREDENTIALS", "1") != "0":
                try:
                    self._proxied = self.http.get(self.probe_url, timeout=6).status_code == 200
                except Exception:
                    self._proxied = False
        return self._proxied

    @property
    def key(self) -> str:
        if self._key:
            return self._key
        if self._probe_proxy_credential():
            return ""          # 키는 프록시가 붙인다 - 이 프로세스는 키를 보지 못함
        raise NotConfigured(f"{self.name}: {self.env_key} 가 설정되지 않았습니다 (환경 변수 또는 환경 자격 증명)")

    def auth_headers(self, header_name: str) -> dict[str, str]:
        k = self.key
        return {header_name: k} if k else {}

    def auth_state(self) -> str:
        if self._key:
            return "set " + mask(self._key)
        return "proxy-injected" if self._probe_proxy_credential() else "missing"

    def configured(self) -> bool:
        if not self.env_key:
            return True
        return bool(self._key) or self._probe_proxy_credential()

    def request_json(self, method: str, url: str, timeout: float = 90, **kw) -> dict:
        try:
            resp = self.http.request(method, url, timeout=timeout, **kw)
        except requests.RequestException as e:
            raise ProviderError(scrub(f"{self.name} 연결 실패: {e}")) from None
        if resp.status_code >= 400:
            raise ProviderError(scrub(f"{self.name} HTTP {resp.status_code}: {resp.text[:300]}"), status=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise ProviderError(f"{self.name}: JSON 응답이 아닙니다") from None

    def health_check(self) -> str:
        """과금 없는 확인 (모델 목록 조회 등). 하위 클래스가 구현."""
        return "configured" if self.configured() else "not_configured"


def timed(fn):
    def wrapper(*a, **kw):
        t = time.monotonic()
        res = fn(*a, **kw)
        if isinstance(res, ProviderResult):
            res.latency = time.monotonic() - t
        return res
    return wrapper
