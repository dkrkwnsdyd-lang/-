"""쿠팡 파트너스 Open API 클라이언트 (정보 전용).

사용 원칙 (사용자 결정)
- 이미지는 사용하지 않는다: 응답의 이미지 필드는 읽지도 저장하지도 않는다.
- 정보(상품명/카테고리/가격/배송 표시/링크)는 '쇼츠를 만들 때'만 쓴다: 상품 데이터베이스를 만들거나 따로 저장하지 않는다 (작업 입력에만 들어감, 메모리 캐시 10분).
- 가격은 조회 시각과 함께 쓰고, 오래되면(24시간) 사실 근거에서 뺀다.
- 키는 .env 의 COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 에서만 읽는다 (코드/로그/화면에 출력하지 않음).

주의: 서명 방식과 엔드포인트는 공식 문서로 검증하지 못한 상태(문서 사이트가 개발 환경에서 차단됨)다. 사용자 PC 에서
`python -m shortsmaker coupang-check` 로 실제 호출을 확인해야 한다. 엔드포인트 후보를 순서대로 시도하고 어떤 것이 통했는지 보고한다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

HOST = "https://api-gateway.coupang.com"
SEARCH_PATHS = ("/v2/providers/affiliate_open_api/apis/openapi/v1/products/search",
                "/v2/providers/affiliate_open_api/apis/openapi/products/search")        # 문서 버전에 따라 v1 유무가 다를 수 있어 둘 다 시도
MIN_INTERVAL = float(os.environ.get("COUPANG_MIN_INTERVAL", "6"))                     # 호출 간 최소 간격(초). 공식 제한은 미확인 → 보수적으로
CACHE_TTL = 600
PRICE_MAX_AGE_HOURS = 24
PUBLIC_FIELDS = ("productId", "productName", "productPrice", "categoryName", "isRocket", "isFreeShipping", "productUrl")   # 이미지 필드는 목록에 없다 = 읽지 않는다


class CoupangNotConfigured(Exception):
    pass


class CoupangError(Exception):
    pass


def keys() -> tuple[str, str]:
    a, s = os.environ.get("COUPANG_ACCESS_KEY", "").strip(), os.environ.get("COUPANG_SECRET_KEY", "").strip()
    if not a or not s:
        raise CoupangNotConfigured(".env 에 COUPANG_ACCESS_KEY 와 COUPANG_SECRET_KEY 를 넣어주세요")
    return a, s


def sign(method: str, path: str, query: str, access: str, secret: str, now: datetime | None = None) -> str:
    """Authorization 헤더 값 (CEA HmacSHA256). 서명 대상 = signed-date + method + path + query('?' 없이)."""
    t = (now or datetime.now(timezone.utc)).strftime("%y%m%dT%H%M%SZ")
    message = t + method.upper() + path + query
    sig = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access}, signed-date={t}, signature={sig}"


_lock = threading.Lock()
_last_call = 0.0
_cache: dict[str, tuple[float, list[dict]]] = {}


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def normalize(item: dict, fetched_at: str) -> dict:
    """응답 한 건 → 사용할 정보만 (이미지 필드는 버린다)."""
    out = {k: item.get(k) for k in PUBLIC_FIELDS}
    price = item.get("productPrice")
    try:
        out["price_krw"] = int(float(price))
    except (TypeError, ValueError):
        out["price_krw"] = None
    out["name"] = str(item.get("productName") or "").strip()
    out["category"] = str(item.get("categoryName") or "").strip()
    out["fetched_at"] = fetched_at
    out["source"] = "coupang_partners_api"
    for k in ("productName", "productPrice", "categoryName"):
        out.pop(k, None)
    return out


def search(keyword: str, limit: int = 5, session=None, paths: tuple[str, ...] = SEARCH_PATHS, use_cache: bool = True) -> dict:
    """상품 검색. 반환: {items, path, fetched_at, cached}. 실패는 CoupangError(원인 포함, 키 값은 포함하지 않음)."""
    keyword = " ".join(keyword.split())[:60]
    if not keyword:
        raise CoupangError("검색어가 비어 있어요")
    access, secret = keys()
    ck = f"{keyword}|{limit}"
    if use_cache and ck in _cache and time.monotonic() - _cache[ck][0] < CACHE_TTL:
        return {"items": _cache[ck][1], "path": "cache", "fetched_at": _cache[ck][1][0]["fetched_at"] if _cache[ck][1] else "", "cached": True}
    http = session or requests
    query = urlencode({"keyword": keyword, "limit": max(1, min(limit, 10))})
    last = ""
    for path in paths:
        _throttle()
        try:
            resp = http.get(HOST + path + "?" + query, headers={"Authorization": sign("GET", path, query, access, secret), "Content-Type": "application/json;charset=UTF-8"},
                            timeout=20)
        except Exception as e:
            raise CoupangError(f"쿠팡 API 연결 실패: {type(e).__name__}") from None
        if resp.status_code in (401, 403):
            raise CoupangError(f"인증 실패(HTTP {resp.status_code}): 키가 올바른지, 파트너스 승인/IP 제한이 있는지 확인해 주세요")
        if resp.status_code == 404:
            last = f"{path} → 404"
            continue
        if resp.status_code >= 400:
            raise CoupangError(f"쿠팡 API 오류(HTTP {resp.status_code})")
        try:
            body = resp.json()
        except ValueError:
            raise CoupangError("쿠팡 API 응답이 JSON 이 아니에요") from None
        if str(body.get("rCode", "0")) not in ("0", "200"):
            raise CoupangError(f"쿠팡 API 거절: rCode={body.get('rCode')} {str(body.get('rMessage', ''))[:80]}")
        data = (body.get("data") or {})
        rows = data.get("productData") if isinstance(data, dict) else None
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        items = [normalize(r, fetched) for r in (rows or []) if isinstance(r, dict)]
        _cache[ck] = (time.monotonic(), items)
        return {"items": items, "path": path, "fetched_at": fetched, "cached": False}
    raise CoupangError("검색 주소를 찾지 못했어요 (" + last + "). 공식 문서의 현재 상품 검색 주소를 확인해야 해요")


def price_is_fresh(meta: dict | None, now: datetime | None = None) -> bool:
    """가격 메타(조회 시각)가 24시간 안인가. 메타가 없거나(사용자 직접 입력) 쿠팡 API 출처가 아니면 True(사용자 책임)."""
    if not meta or meta.get("source") != "coupang_partners_api":
        return True
    try:
        t = datetime.fromisoformat(meta["fetched_at"])
    except (KeyError, ValueError):
        return False
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() <= PRICE_MAX_AGE_HOURS * 3600


def check(session=None) -> dict:
    """연결 점검: 키가 있는지, 서명이 통하는지, 어떤 검색 주소가 응답하는지. 키 값은 출력하지 않는다."""
    try:
        keys()
    except CoupangNotConfigured as e:
        return {"ok": False, "stage": "keys", "message": str(e)}
    try:
        r = search("텀블러", 1, session=session, use_cache=False)
    except CoupangError as e:
        return {"ok": False, "stage": "call", "message": str(e)}
    return {"ok": True, "stage": "done", "path": r["path"], "items": len(r["items"]), "sample_name": (r["items"][0]["name"][:30] if r["items"] else ""),
            "message": "서명과 검색 주소가 통했어요" + ("" if r["items"] else " (검색 결과는 0건)")}
