"""UGC Reference Mode 오케스트레이션 + 저장(DB). 각 단계 결과를 저장해서 새로고침/재접속 후에도 이어서 쓴다 (PC↔모바일 공유).

무거운 분석은 `analyze_and_store` 호출 시에만 실행된다 (Mode OFF 에서는 이 모듈이 import 되지도 않는다).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ..product import ProductInput
from ..strategy import make_ctx
from ..strategy.common import line_issues, strip_marks
from . import analyzer, concepts as concepts_mod, mixer, prompts, storyboard as sb_mod

MAX_REFERENCES = 5
PRODUCT_FIELDS = ("name", "description", "features", "problem", "target", "price", "category_hint", "my_take", "review_quotes", "before_after", "photos")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ references
def analyze_and_store(db, router, *, file: str = "", url: str = "", notes: str = "") -> dict:
    r = analyzer.analyze(router, file=file, url=url, notes=notes)
    db.execute("INSERT INTO ugc_references (id, source_kind, source_ref, status, analysis_json, fingerprint_json, error, created_at) VALUES (?,?,?,?,?,?,?,?)",
               (r["id"], r["source_kind"], r["source_ref"], r["status"], json.dumps(r["analysis"], ensure_ascii=False) if r["analysis"] else None,
                json.dumps(r["fingerprint"]), r["error"], r["created_at"]))
    return public_reference(r)


def public_reference(r: dict) -> dict:
    """화면/API 로 내보낼 형태 (복제 방지 해시는 내보내지 않는다)."""
    return {k: r.get(k) for k in ("id", "source_kind", "source_ref", "status", "analysis", "error", "method", "created_at")}


def get_references(db, ids: list[str]) -> list[dict]:
    out = []
    for i in ids[:MAX_REFERENCES]:
        rows = db.query("SELECT * FROM ugc_references WHERE id=?", (i,))
        if rows:
            r = rows[0]
            out.append({"id": r["id"], "source_kind": r["source_kind"], "source_ref": r["source_ref"], "status": r["status"], "error": r["error"] or "",
                        "analysis": json.loads(r["analysis_json"]) if r["analysis_json"] else None, "fingerprint": json.loads(r["fingerprint_json"] or "[]")})
    return out


# ------------------------------------------------------------------ sessions
def _product(d: dict) -> ProductInput:
    return ProductInput.from_dict({k: v for k, v in d.items() if k in PRODUCT_FIELDS and k != "photos"})


def _ctx(product: dict, mixed_fp: list[str] | None = None):
    p = _product(product)
    return make_ctx(p, "UGC_REVIEW", "PRO", None, None, has_clip=False, pattern={"fingerprint": mixed_fp or [], "story": {}, "hook": {}}), p


def create_session(db, router, product: dict, reference_ids: list[str]) -> dict:
    """레퍼런스(성공한 것만) → Reference Mixer → 콘셉트 3개. 반환: 세션 전체."""
    if not (product.get("name") or "").strip():
        raise ValueError("상품명이 필요해요")
    if not reference_ids:
        raise ValueError("레퍼런스를 1개 이상 선택하세요 (최대 5개)")
    refs = get_references(db, reference_ids)
    ctx, p = _ctx(product)
    mixed = mixer.mix(refs, ctx)
    if not mixed["adopted"]:
        raise ValueError("분석에 성공한 레퍼런스가 없어요: " + "; ".join(r["error"] for r in refs if r.get("error"))[:200])
    ctx, p = _ctx(product, mixed["fingerprint"])
    cres = concepts_mod.generate(router, ctx, mixed)
    sid = "us_" + uuid.uuid4().hex[:10]
    now = _now()
    db.execute("INSERT INTO ugc_sessions (id, product_json, reference_ids, mixer_json, concepts_json, selected_concept, storyboard_json, package_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (sid, json.dumps(product, ensure_ascii=False), json.dumps(reference_ids), json.dumps(mixed, ensure_ascii=False), json.dumps(cres, ensure_ascii=False), None, None, None, now, now))
    return get_session(db, sid)


def get_session(db, sid: str) -> dict | None:
    rows = db.query("SELECT * FROM ugc_sessions WHERE id=?", (sid,))
    if not rows:
        return None
    r = rows[0]
    j = lambda k: json.loads(r[k]) if r[k] else None
    mixed = j("mixer_json")
    return {"id": r["id"], "product": j("product_json"), "reference_ids": j("reference_ids"), "mixer": {k: v for k, v in (mixed or {}).items() if k != "fingerprint"},
            "concepts": j("concepts_json"), "selected_concept": r["selected_concept"], "storyboard": j("storyboard_json"), "package": j("package_json"),
            "created_at": r["created_at"], "updated_at": r["updated_at"], "_fingerprint": (mixed or {}).get("fingerprint", [])}


def public_session(s: dict) -> dict:
    return {k: v for k, v in s.items() if not k.startswith("_")}


def list_sessions(db, limit: int = 20) -> list[dict]:
    rows = db.query("SELECT id, product_json, selected_concept, updated_at FROM ugc_sessions ORDER BY updated_at DESC LIMIT ?", (limit,))
    return [{"id": r["id"], "name": (json.loads(r["product_json"]) or {}).get("name", ""), "selected_concept": r["selected_concept"], "updated_at": r["updated_at"]} for r in rows]


def _category(ctx) -> str:
    return ctx.category


def select_concept(db, router, sid: str, concept_id: str, product_reference: str | None = None) -> dict:
    s = get_session(db, sid)
    if not s:
        raise KeyError("세션 없음")
    concept = next((c for c in (s["concepts"] or {}).get("concepts", []) if c["id"] == concept_id), None)
    if not concept:
        raise ValueError("없는 콘셉트예요")
    mixed = json.loads(db.query("SELECT mixer_json FROM ugc_sessions WHERE id=?", (sid,))[0]["mixer_json"])
    ctx, _ = _ctx(s["product"], s["_fingerprint"])
    board = sb_mod.build(ctx, concept, mixed)
    pkg = prompts.build_package(ctx, concept, board, _category(ctx), product_reference)
    _save(db, sid, selected=concept_id, board=board, package=pkg)
    return public_session(get_session(db, sid))


def _save(db, sid: str, selected: str | None = None, board: dict | None = None, package: dict | None = None) -> None:
    db.execute("UPDATE ugc_sessions SET selected_concept=COALESCE(?, selected_concept), storyboard_json=COALESCE(?, storyboard_json), package_json=COALESCE(?, package_json), updated_at=? WHERE id=?",
               (selected, json.dumps(board, ensure_ascii=False) if board is not None else None, json.dumps(package, ensure_ascii=False) if package is not None else None, _now(), sid))


EDITABLE = ("voice_over", "caption", "video_prompt", "visual", "person_action", "product_action", "camera_shot", "camera_movement", "sfx")


def edit_scenes(db, sid: str, edits: dict) -> dict:
    """edits = {scene_number(str): {field: value}}. 대사/자막은 사실 안전 규칙(근거 없는 주장/가짜 경험/복제)을 통과해야 반영, 아니면 이유와 함께 거부."""
    s = get_session(db, sid)
    if not s or not s["storyboard"]:
        raise ValueError("스토리보드가 없어요 (콘셉트를 먼저 선택하세요)")
    ctx, _ = _ctx(s["product"], s["_fingerprint"])
    board, applied, rejected = s["storyboard"], [], []
    for num, fields in (edits or {}).items():
        sc = next((x for x in board["scenes"] if str(x["scene_number"]) == str(num)), None)
        if not sc:
            rejected.append({"scene": num, "why": "없는 장면"})
            continue
        for k, v in (fields or {}).items():
            if k not in EDITABLE:
                continue
            v = " ".join(str(v).split())[:600]
            if k in ("voice_over", "caption"):
                bad = [i for i in line_issues(strip_marks(v), ctx) if i["severity"] == "block"]
                if bad:
                    rejected.append({"scene": num, "field": k, "why": f"규칙 위반({bad[0]['code']}: {bad[0]['detail']}) - 입력에 없는 사실/사용 경험/상투구는 쓸 수 없어요"})
                    continue
            if k == "camera_shot" and v not in sb_mod.SHOT_KO:
                rejected.append({"scene": num, "field": k, "why": "지원하지 않는 샷 크기"})
                continue
            if k == "camera_movement" and v not in sb_mod.MOVE_KO:
                rejected.append({"scene": num, "field": k, "why": "지원하지 않는 카메라 움직임"})
                continue
            sc[("video_prompt_override" if k == "video_prompt" else k)] = v
            applied.append({"scene": num, "field": k})
    concept = next(c for c in s["concepts"]["concepts"] if c["id"] == s["selected_concept"])
    pkg = prompts.build_package(ctx, concept, board, _category(ctx), (s["package"] or {}).get("product_reference", {}).get("image"))
    for sp, sc in zip(pkg["scenes"], board["scenes"]):          # 사용자가 직접 고친 프롬프트는 그대로 보존
        if sc.get("video_prompt_override"):
            sp["video_prompt"] = sc["video_prompt_override"]
        sc_prompt_vo = [sc["voice_over"], sc["caption"]]
        sp["voice_over"], sp["caption"] = sc_prompt_vo
    pkg["voice_script"] = [x["voice_over"] for x in pkg["scenes"]]
    pkg["captions"] = [x["caption"] for x in pkg["scenes"]]
    pkg["cta"] = pkg["scenes"][-1]["voice_over"]
    _save(db, sid, board=board, package=pkg)
    return {"session": public_session(get_session(db, sid)), "applied": applied, "rejected": rejected, "separation_problems": prompts.check_separation(pkg)}
