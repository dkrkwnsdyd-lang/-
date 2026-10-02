"""raw 분석 → PATTERN (추상 값만) + 점수 + 라이브러리 태그. 원문/고유 문구는 여기서 버린다."""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timezone

from ..storyboard.scene_director import DATA_CLAIM
from . import fingerprint, vocab


def _pick(v, allowed, default=None):
    if isinstance(v, str) and v in allowed:
        return v
    return default


def _list(v, allowed, limit=6):
    out = []
    for x in (v or []) if isinstance(v, list) else []:
        if isinstance(x, str) and x in allowed and x not in out:
            out.append(x)
    return out[:limit]


def _num(v, lo=0.0, hi=600.0):
    try:
        return round(max(lo, min(hi, float(v))), 2)
    except (TypeError, ValueError):
        return None


def _label(v, n=30):
    """추상 라벨(한국어 30자 이내). 수치/가격/할인 같은 데이터성 표현이 있으면 버린다 (현재 상품의 사실로 오해되지 않도록)."""
    if not isinstance(v, str):
        return ""
    t = re.sub(r"\s+", " ", v).strip()
    if not t or DATA_CLAIM.search(t) or len(t) > n * 2:
        return ""
    return t[:n]


def classify(p: dict) -> list[str]:
    """라이브러리 태그(PROBLEM_STORY 등). 규칙 기반 — 필드에서 결정적으로 도출."""
    stages = p.get("story_stages") or []
    reveal = p.get("product_reveal_time")
    style = p.get("content_style")
    tags = []
    if "problem" in stages and stages.index("problem") < (stages.index("product_reveal") if "product_reveal" in stages else 99):
        tags.append("PROBLEM_STORY")
    if reveal is not None and reveal <= 3.5:
        tags.append("FAST_REVEAL")
    if reveal is not None and reveal >= 7.0 or ("product_reveal" in stages and stages.index("product_reveal") >= 5):
        tags.append("LATE_PRODUCT_REVEAL")
    if style == "ugc" or p.get("hook_pattern") in ("pov", "direct_address") and style in ("ugc", "lifestyle"):
        tags.append("UGC_DISCOVERY")
    if style == "before_after":
        tags.append("BEFORE_AFTER")
    if ("emotion" in stages and "turning_point" in stages) or p.get("emotion_curve") == "dip_then_rise" and style == "story":
        tags.append("EMOTIONAL_STORY")
    if style == "comparison":
        tags.append("COMPARISON")
    if style == "demo" or "demo" in stages and style not in ("story", "lifestyle"):
        tags.append("DEMO")
    if style == "lifestyle":
        tags.append("LIFESTYLE")
    return [t for t in dict.fromkeys(tags) if t in vocab.LIBRARY_TAGS] or ["DEMO"]


def tempo_regularity(local: dict) -> float | None:
    """컷 길이 변동계수가 낮을수록(리듬이 일정/의도적) 높은 편집 점수 기여. 컷이 너무 적으면 None."""
    cuts = local.get("cut_times") or []
    dur = local.get("duration") or 0
    if dur <= 0 or len(cuts) < 3:
        return None
    b = [0.0] + cuts + [dur]
    ln = [y - x for x, y in zip(b, b[1:]) if y - x > 0.05]
    if len(ln) < 3:
        return None
    cv = statistics.pstdev(ln) / (statistics.mean(ln) or 1)
    return round(max(0.0, min(100.0, 100 - 55 * cv)), 1)


def build(analysis: dict, category: str = "") -> dict:
    """analysis(analyzer.analyze 결과) → {pattern, scores, confidence, fingerprint, library_tags, status, platform ...}."""
    d = analysis.get("data") or {}
    local = analysis.get("local") or {}
    transcript = " ".join(str(d.get(k) or "") for k in ("_transcript", "_captions"))
    fp = fingerprint.make([d.get("_transcript") or "", d.get("_captions") or ""]) if transcript.strip() else []
    dur = _num(d.get("video_duration")) or local.get("duration")
    scene_count = d.get("scene_count") if isinstance(d.get("scene_count"), int) and d.get("scene_count") > 0 else local.get("scene_count")
    avg_scene = local.get("avg_scene") or _num(d.get("average_scene_duration"), 0.3, 10) or (round(dur / scene_count, 2) if dur and scene_count else None)
    stages = _list(d.get("story_stages"), vocab.STORY_STAGES, 10)
    roles_in = d.get("story_roles") if isinstance(d.get("story_roles"), dict) else {}
    pattern = {
        "hook_pattern": _pick(d.get("hook_pattern"), vocab.HOOK_PATTERNS), "hook_duration": _num(d.get("hook_duration"), 0, 10),
        "video_duration": dur, "scene_count": scene_count, "average_scene_duration": avg_scene,
        "story_stages": stages, "product_reveal_time": _num(d.get("product_reveal_time")),
        "caption_density": _pick(d.get("caption_density"), vocab.CAPTION_DENSITY), "caption_position": _pick(d.get("caption_position"), vocab.CAPTION_POSITIONS),
        "caption_pattern": _pick(d.get("caption_pattern"), vocab.CAPTION_PATTERNS), "caption_change_frequency": _pick(d.get("caption_change_frequency"), vocab.CAPTION_CHANGE),
        "camera_motion": _list(d.get("camera_motion"), vocab.MOTION_PATTERNS), "image_motion": _list(d.get("image_motion"), vocab.MOTION_PATTERNS),
        "transition_pattern": _list(d.get("transition_pattern"), vocab.TRANSITION_PATTERNS), "sfx_pattern": _pick(d.get("sfx_pattern"), vocab.SFX_PATTERNS),
        "bgm_mood": _pick(d.get("bgm_mood"), vocab.BGM_MOODS), "cta_pattern": _pick(d.get("cta_pattern"), vocab.CTA_PATTERNS), "cta_position": _num(d.get("cta_position")),
        "content_style": _pick(d.get("content_style"), vocab.CONTENT_STYLES), "emotion_curve": _pick(d.get("emotion_curve"), vocab.EMOTION_CURVES),
        "selling_structure": _label(d.get("selling_structure")),
        "story_roles": {k: _label(roles_in.get(k)) for k in ("situation", "problem", "emotion", "turning_point", "product_role", "result", "cta")},
        "language": _pick(d.get("language"), ("ko", "zh", "en", "other")),
    }
    if "hook" not in stages and stages:
        pattern["story_stages"] = ["hook"] + stages
    sc_in = d.get("scores") if isinstance(d.get("scores"), dict) else {}
    scores = {k: _num(sc_in.get(k), 0, 100) for k in vocab.SCORE_KEYS if k != "product_fit"}
    reg = tempo_regularity(local)
    if reg is not None:                                              # 측정 가능한 편집 지표는 LLM 점수에 섞는다 (후한 점수 방지)
        scores["editing_quality"] = round(0.5 * (scores.get("editing_quality") or reg) + 0.5 * reg, 1)
    filled = sum(1 for k, v in pattern.items() if v not in (None, "", [], {}) and k != "story_roles")
    total = len(pattern) - 1
    confidence = round(min(1.0, filled / total) * {"VERIFIED": 1.0, "PARTIAL": 0.7}.get(analysis.get("status"), 0.3), 2)
    return {"platform": analysis.get("platform", "other"), "source_ref": analysis.get("source_ref", ""), "category": category, "status": analysis.get("status", "UNVERIFIED"),
            "pattern": pattern, "scores": scores, "confidence": confidence, "fingerprint": fp, "library_tags": classify(pattern) if stages or pattern.get("content_style") else [],
            "method": analysis.get("method"), "note": analysis.get("note", ""), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
