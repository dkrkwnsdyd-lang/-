"""PATTERN MIX ENGINE: 여러 Reference 의 '장점 패턴'만 조합한다 (영상/대본을 합치는 것이 아님).

AUTO: 영역별로 점수가 가장 높은 Reference 를 고른다. 플랫폼 강점(YouTube=Hook/CTA, Reels=템포/자막/모션, 샤오홍슈=스토리/감정) 가산점,
현재 상품과의 적합도(product_fit)를 반영. 수동: picks={"hook": id, "story": id, "tempo": id, "cta": id}
"""
from __future__ import annotations

from . import library
from .vocab import PLATFORM_STRENGTH

ASPECTS = ("hook", "story", "tempo", "cta")
ASPECT_SCORE = {"hook": "hook_strength", "story": "story_strength", "tempo": "editing_quality", "cta": "sales_connection"}
ASPECT_BONUS = {"hook": ("hook",), "story": ("story", "emotion"), "tempo": ("tempo", "caption", "motion"), "cta": ("cta",)}
ASPECT_FIELDS = {
    "hook": ("hook_pattern", "hook_duration"),
    "story": ("story_stages", "story_roles", "emotion_curve", "content_style", "product_reveal_time", "selling_structure"),
    "tempo": ("average_scene_duration", "scene_count", "video_duration", "caption_density", "caption_position", "caption_pattern", "caption_change_frequency",
              "camera_motion", "image_motion", "transition_pattern", "sfx_pattern", "bgm_mood"),
    "cta": ("cta_pattern", "cta_position"),
}


def _aspect_score(aspect: str, rec: dict, ctx) -> float:
    base = float(rec["scores"].get(ASPECT_SCORE[aspect]) or 0.0)
    if any(b in ASPECT_BONUS[aspect] for b in PLATFORM_STRENGTH.get(rec["platform"], ())):
        base += 8 if aspect == "story" else 6
    fit = library.product_fit(rec, ctx) if ctx is not None else 50.0
    usable = 1.0
    p = rec["pattern"]
    if aspect == "story" and len(p.get("story_stages") or []) < 3:
        usable = 0.0                       # 스토리 구조를 알 수 없는 Reference 는 스토리 기여 후보에서 제외
    if aspect == "hook" and not p.get("hook_pattern"):
        usable = 0.0
    if aspect == "tempo" and not p.get("average_scene_duration"):
        usable = 0.0
    if aspect == "cta" and not p.get("cta_pattern"):
        usable = 0.0
    return (base * 0.8 + fit * 0.2) * usable + 0.01 * (rec.get("confidence") or 0)


def mix(recs: list[dict], ctx=None, picks: dict | None = None) -> dict:
    """recs: library.get(...) 결과 목록(핑거프린트 포함). 반환: {aspects:{aspect:{from,platform,score,reason}}, values:{...}, fingerprint:[...], sources:[...]}"""
    if not recs:
        return {}
    by_id = {r["id"]: r for r in recs}
    aspects, values = {}, {}
    for a in ASPECTS:
        chosen = by_id.get((picks or {}).get(a)) if picks else None
        if chosen:
            reason = "사용자가 선택"
            sc = _aspect_score(a, chosen, ctx)
        else:
            ranked = sorted(recs, key=lambda r: -_aspect_score(a, r, ctx))
            chosen, sc = ranked[0], _aspect_score(a, ranked[0], ctx)
            reason = f"{a} 점수 {sc:.0f} 최고 ({chosen['platform_ko']})"
            if sc < 1:                                   # 이 영역을 쓸 수 있는 Reference 가 없다
                aspects[a] = {"from": None, "reason": "이 영역을 알 수 있는 Reference 가 없어 기본값 사용"}
                continue
        aspects[a] = {"from": chosen["id"], "platform": chosen["platform"], "score": round(sc, 1), "reason": reason}
        for f in ASPECT_FIELDS[a]:
            values[f] = chosen["pattern"].get(f)
    fp: set[str] = set()
    for r in recs:
        fp |= set(r.get("fingerprint") or [])
    return {"aspects": aspects, "values": values, "fingerprint": sorted(fp), "sources": [{"id": r["id"], "platform": r["platform"], "tags": r["library_tags"]} for r in recs]}
