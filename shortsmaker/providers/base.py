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
    pass


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

    def __init__(self, session: requests.Session | None = None, api_key: str | None = None):
        self.http = session or requests.Session()
        self._key = api_key if api_key is not None else (os.environ.get(self.env_key) if self.env_key else None)

    @property
    def key(self) -> str:
        if not self._key:
            raise NotConfigured(f"{self.name}: {self.env_key} 가 설정되지 않았습니다 (.env)")
        return self._key

    def configured(self) -> bool:
        return bool(self._key) if self.env_key else True

    def request_json(self, method: str, url: str, timeout: float = 90, **kw) -> dict:
        try:
            resp = self.http.request(method, url, timeout=timeout, **kw)
        except requests.RequestException as e:
            raise ProviderError(scrub(f"{self.name} 연결 실패: {e}")) from None
        if resp.status_code >= 400:
            raise ProviderError(scrub(f"{self.name} HTTP {resp.status_code}: {resp.text[:300]}"))
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
