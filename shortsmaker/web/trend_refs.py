"""트렌드 레퍼런스 API: 브라우저 확장(레퍼런스 인사이트)이 모은 레퍼런스를 받아 둔다.

- 저장하는 것은 링크와 공개 숫자(좋아요·저장·댓글, 성과배수, 점수)뿐이다. 본문·영상·이미지는 받지 않는다.
- 같은 게시물을 다시 보내면 숫자만 새로 고친다.
- 인증은 앱 전체 규칙을 따른다 (로컬 전용이면 없음, 암호가 있으면 쿠키 또는 `Authorization: Bearer <암호>`).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..db import now

STATIC = Path(__file__).parent / "static"
PLATFORMS = ("xiaohongshu", "youtube", "instagram", "tiktok", "threads")
MAX_ITEMS = 500
ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


class TrendRefsRequest(BaseModel):
    items: list  # 항목 하나가 이상해도 전체를 거부하지 않고 그 항목만 건너뛴다


def _int(v):
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _text(v, limit: int) -> str:
    return str(v or "").strip()[:limit]


def clean(item: dict) -> dict | None:
    """확장에서 온 항목 하나를 검사·정리한다. 쓸 수 없으면 None."""
    if not isinstance(item, dict):
        return None
    sid = str(item.get("id") or "")
    url = _text(item.get("url"), 500)
    platform = item.get("platform") or "xiaohongshu"
    if not ID_RE.match(sid) or platform not in PLATFORMS or not url.startswith("https://"):
        return None
    score = _int(item.get("score"))
    return {
        "id": f"{platform}:{sid}", "platform": platform, "source_id": sid, "url": url,
        "title": _text(item.get("title"), 200), "author": _text(item.get("author"), 100),
        "likes": _int(item.get("likes")), "collects": _int(item.get("collects")), "comments": _int(item.get("comments")),
        "mult": _float(item.get("mult")), "score": max(0, min(100, score)) if score is not None else None,
        "tier": _text(item.get("tier"), 20), "context": _text(item.get("context"), 200), "saved_at": _text(item.get("savedAt"), 40),
    }


def register_trend_refs(app: FastAPI, db) -> None:
    @app.get("/trends")
    def trends_page():
        return FileResponse(STATIC / "trends.html")

    @app.post("/api/v2/trend-refs")
    def add_trend_refs(req: TrendRefsRequest):
        if len(req.items) > MAX_ITEMS:
            raise HTTPException(400, f"한 번에 {MAX_ITEMS}개까지 보낼 수 있습니다.")
        added = updated = skipped = 0
        ts = now()
        for raw in req.items:
            r = clean(raw)
            if not r:
                skipped += 1
                continue
            exists = db.query("SELECT 1 FROM trend_refs WHERE id=?", (r["id"],))
            if exists:
                db.execute("UPDATE trend_refs SET url=?, title=?, author=?, likes=?, collects=?, comments=?, mult=?, score=?, tier=?, "
                           "context=?, saved_at=?, updated_at=? WHERE id=?",
                           (r["url"], r["title"], r["author"], r["likes"], r["collects"], r["comments"], r["mult"], r["score"], r["tier"],
                            r["context"], r["saved_at"], ts, r["id"]))
                updated += 1
            else:
                db.execute("INSERT INTO trend_refs (id, platform, source_id, url, title, author, likes, collects, comments, mult, score, tier, "
                           "context, saved_at, imported_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (r["id"], r["platform"], r["source_id"], r["url"], r["title"], r["author"], r["likes"], r["collects"], r["comments"],
                            r["mult"], r["score"], r["tier"], r["context"], r["saved_at"], ts, ts))
                added += 1
        return {"added": added, "updated": updated, "skipped": skipped,
                "total": db.query("SELECT COUNT(*) AS n FROM trend_refs")[0]["n"]}

    @app.get("/api/v2/trend-refs")
    def list_trend_refs(platform: str = "", limit: int = 200):
        limit = max(1, min(limit, 500))
        if platform and platform in PLATFORMS:
            rows = db.query("SELECT * FROM trend_refs WHERE platform=? ORDER BY mult DESC, imported_at DESC LIMIT ?", (platform, limit))
        else:
            rows = db.query("SELECT * FROM trend_refs ORDER BY mult DESC, imported_at DESC LIMIT ?", (limit,))
        return rows

    @app.delete("/api/v2/trend-refs/{rid}")
    def delete_trend_ref(rid: str):
        if not db.execute("DELETE FROM trend_refs WHERE id=?", (rid,)).rowcount:
            raise HTTPException(404, "없는 레퍼런스입니다.")
        return {"ok": True}
