"""PATTERN LIBRARY: 분석한 패턴을 DB(`reference_patterns`)에 저장/조회. 원본 대사·영상은 저장하지 않는다."""
from __future__ import annotations

import json
import uuid

from . import vocab


def save_draft(db, built: dict, rights: str = "NONE") -> str:
    pid = "rp_" + uuid.uuid4().hex[:10]
    db.execute("INSERT INTO reference_patterns (id, platform, source_ref, category, status, saved, library_tags, pattern_json, scores_json, confidence, "
               "fingerprint_json, rights, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (pid, built["platform"], built["source_ref"], built.get("category", ""), built["status"], 0, json.dumps(built["library_tags"], ensure_ascii=False),
                json.dumps(built["pattern"], ensure_ascii=False), json.dumps(built["scores"]), built["confidence"], json.dumps(built["fingerprint"]),
                rights if rights in ("OWNED", "LICENSED") else "NONE", built["created_at"]))
    return pid


def _row(r: dict, with_fp: bool = True) -> dict:
    out = {"id": r["id"], "platform": r["platform"], "platform_ko": vocab.PLATFORM_KO.get(r["platform"], r["platform"]), "source_ref": r["source_ref"],
           "category": r["category"], "status": r["status"], "saved": bool(r["saved"]), "library_tags": json.loads(r["library_tags"] or "[]"),
           "pattern": json.loads(r["pattern_json"] or "{}"), "scores": json.loads(r["scores_json"] or "{}"), "confidence": r["confidence"],
           "rights": r["rights"], "created_at": r["created_at"]}
    if with_fp:
        out["fingerprint"] = json.loads(r["fingerprint_json"] or "[]")
    return out


def get(db, pid: str, with_fp: bool = True) -> dict | None:
    rows = db.query("SELECT * FROM reference_patterns WHERE id=?", (pid,))
    return _row(rows[0], with_fp) if rows else None


def get_many(db, ids: list[str]) -> list[dict]:
    return [r for r in (get(db, i) for i in ids) if r]


def list_patterns(db, saved_only: bool = True, tag: str | None = None, platform: str | None = None) -> list[dict]:
    rows = db.query("SELECT * FROM reference_patterns " + ("WHERE saved=1 " if saved_only else "") + "ORDER BY created_at DESC LIMIT 200")
    out = [_row(r, with_fp=False) for r in rows]
    if tag:
        out = [r for r in out if tag in r["library_tags"]]
    if platform:
        out = [r for r in out if r["platform"] == platform]
    return out


def mark_saved(db, pid: str) -> bool:
    cur = db.execute("UPDATE reference_patterns SET saved=1 WHERE id=?", (pid,))
    return cur.rowcount > 0


def delete(db, pid: str) -> bool:
    return db.execute("DELETE FROM reference_patterns WHERE id=?", (pid,)).rowcount > 0


def product_fit(rec: dict, ctx) -> float:
    """현재 상품과 패턴의 적합도 0~100 (조회수가 아니라 '이 상품에 쓸 수 있는가').
    사실 안전: 문제/상황 단계가 있는 패턴은 입력에 문제가 있어야 쓸 수 있고, 전/후·비교 패턴은 사용자 데이터가 있어야 한다."""
    p, tags, stages = rec["pattern"], rec["library_tags"], rec["pattern"].get("story_stages") or []
    s = 55.0
    needs_problem = any(x in stages for x in ("situation", "problem", "emotion", "turning_point"))
    if needs_problem:
        s += 15 if ctx.p.problem.strip() else -22
    if rec.get("category") and rec["category"] == ctx.category:
        s += 12
    if "BEFORE_AFTER" in tags and not ctx.p.before_after:
        s -= 28
    if "COMPARISON" in tags and not ctx.p.comparison:
        s -= 28
    if "UGC_DISCOVERY" in tags and not (ctx.has_clip or getattr(ctx.p, "my_take", "")):
        s -= 6
    if (p.get("product_reveal_time") or 0) > 9 and len(ctx.p.features) < 2:
        s -= 10                                   # 늦은 공개는 보여줄 내용이 충분할 때만
    s *= 0.6 + 0.4 * (rec.get("confidence") or 0.3)
    return round(max(0.0, min(100.0, s)), 1)


def recommend(db, ctx, limit: int = 5) -> list[dict]:
    recs = list_patterns(db, saved_only=True)
    for r in recs:
        r["product_fit"] = product_fit(r, ctx)
    return sorted(recs, key=lambda r: -r["product_fit"])[:limit]
