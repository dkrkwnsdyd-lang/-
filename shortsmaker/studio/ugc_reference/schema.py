"""UGC Reference Mode: referenceAnalysis 구조화 스키마. 값은 어휘(enum)/숫자/짧은 추상 라벨만 (원본 대사·자막 저장 금지)."""
from __future__ import annotations

import re

from ..storyboard.scene_director import DATA_CLAIM

HOOK_PATTERNS = ("problem_first", "question", "curiosity_gap", "empathy", "shock_visual", "demo_first", "result_first", "direct_address", "pov", "other")
ATTENTION = ("text_overlay", "face_closeup", "motion", "question", "shock_visual", "result_first", "sound_cue", "pov", "product_closeup")
PERSON_MODES = ("selfie", "pov", "hands_only", "talking_head", "none")
GAZE = ("camera", "product", "away")
AUTHENTICITY = ("handheld_shake", "natural_light", "casual_room", "imperfect_framing", "direct_address", "casual_speech")
USP_EMPHASIS = ("text_overlay", "closeup", "voice", "demo", "none")
SHOT_SIZES = ("extreme_close_up", "close_up", "medium", "wide")
ANGLES = ("eye_level", "high", "low", "top_down", "pov")
MOVEMENTS = ("handheld", "zoom", "push_in", "pan", "tilt", "static")
CUT_SPEED = ("slow", "medium", "fast")
CAPTION_POS = ("top", "center", "bottom")
SFX = ("none", "sparse", "frequent")
BGM = ("energetic", "calm", "cinematic", "acoustic", "trending_beat", "none")
STAGES = ("hook", "problem", "agitation", "solution", "demonstration", "proof", "benefit", "cta")
STAGE_KO = {"hook": "Hook", "problem": "Problem", "agitation": "Agitation", "solution": "Solution", "demonstration": "Demonstration", "proof": "Proof", "benefit": "Benefit", "cta": "CTA"}
CTA_STYLES = ("soft_recommendation", "direct_link", "question", "scarcity", "none")
SCORE_KEYS = ("hook_strength", "ugc_authenticity", "demonstration_clarity", "editing_quality", "sales_connection")


def _pick(v, allowed, default=None):
    return v if isinstance(v, str) and v in allowed else default


def _list(v, allowed, limit=6):
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, str) and x in allowed and x not in out:
            out.append(x)
    return out[:limit]


def _num(v, lo=0.0, hi=600.0):
    try:
        return round(max(lo, min(hi, float(v))), 2)
    except (TypeError, ValueError):
        return None


def _bool(v):
    return bool(v) if isinstance(v, (bool, int)) else None


def _label(v, n=40):
    """추상 라벨. 수치/가격/할인/평점 같은 데이터성 표현이 있거나 너무 길면(원문 인용 의심) 버린다."""
    if not isinstance(v, str):
        return ""
    t = re.sub(r"\s+", " ", v).strip()
    if not t or DATA_CLAIM.search(t) or len(t) > n * 2:
        return ""
    return t[:n]


def normalize(d: dict, local: dict | None = None) -> dict:
    """LLM raw → referenceAnalysis. 알 수 없는 값은 None/빈 값 (지어내지 않음)."""
    d = d if isinstance(d, dict) else {}
    local = local or {}
    h, up, pr, cam, ed = (d.get(k) if isinstance(d.get(k), dict) else {} for k in ("hook", "ugc_person", "product", "camera", "editing"))
    struct = []
    for s in d.get("structure") if isinstance(d.get("structure"), list) else []:
        if isinstance(s, dict) and s.get("stage") in STAGES:
            struct.append({"stage": s["stage"], "start": _num(s.get("start")), "end": _num(s.get("end"))})
    avg_cut = local.get("avg_scene") or _num(ed.get("avg_cut"), 0.2, 20)
    sc_in = d.get("scores") if isinstance(d.get("scores"), dict) else {}
    out = {
        "version": 1,
        "hook": {"first_1s": _label(h.get("first_1s")), "first_3s": _label(h.get("first_3s")), "first_scene": _label(h.get("first_scene")),
                 "attention_devices": _list(h.get("attention_devices"), ATTENTION), "problem_raised": _bool(h.get("problem_raised")), "curiosity": _bool(h.get("curiosity")),
                 "twist": _bool(h.get("twist")), "result_first": _bool(h.get("result_first")), "pattern": _pick(h.get("hook_pattern"), HOOK_PATTERNS)},
        "ugc_person": {"face_visible": _bool(up.get("face_visible")), "mode": _pick(up.get("mode"), PERSON_MODES), "expression": _label(up.get("expression"), 24),
                       "gaze": _pick(up.get("gaze"), GAZE), "gestures": [g for g in (_label(x, 20) for x in (up.get("gestures") or [])[:4]) if g],
                       "product_grip": _label(up.get("product_grip"), 24), "authenticity_cues": _list(up.get("authenticity_cues"), AUTHENTICITY)},
        "product": {"first_appearance": _num(pr.get("first_appearance")), "closeup": _bool(pr.get("closeup")), "usage_process": _bool(pr.get("usage_process")),
                    "demonstration": _bool(pr.get("demonstration")), "before_after": _bool(pr.get("before_after")), "result_screen": _bool(pr.get("result_screen")),
                    "usp_emphasis": _pick(pr.get("usp_emphasis"), USP_EMPHASIS)},
        "camera": {"shot_sizes": _list(cam.get("shot_sizes"), SHOT_SIZES), "angles": _list(cam.get("angles"), ANGLES), "movements": _list(cam.get("movements"), MOVEMENTS)},
        "editing": {"avg_cut": avg_cut, "cut_speed": _pick(ed.get("cut_speed"), CUT_SPEED), "text_timing": _num(ed.get("text_timing"), 0, 60),
                    "caption_position": _pick(ed.get("caption_position"), CAPTION_POS), "emphasis_caption": _bool(ed.get("emphasis_caption")),
                    "screen_zoom": _bool(ed.get("screen_zoom")), "sfx": _pick(ed.get("sfx"), SFX), "bgm_mood": _pick(ed.get("bgm_mood"), BGM)},
        "cta": {"style": _pick((d.get("cta") or {}).get("style") if isinstance(d.get("cta"), dict) else None, CTA_STYLES), "position": _num((d.get("cta") or {}).get("position") if isinstance(d.get("cta"), dict) else None)},
        "structure": struct,
        "emotional_tone": _label(d.get("emotional_tone"), 30),
        "useful_patterns": [x for x in (_label(p, 40) for p in (d.get("useful_patterns") or [])[:6]) if x],
        "scores": {k: _num(sc_in.get(k), 0, 100) for k in SCORE_KEYS},
        "video_duration": _num(d.get("video_duration")) or local.get("duration"), "language": _pick(d.get("language"), ("ko", "zh", "en", "other")),
    }
    return out


def filled_ratio(a: dict) -> float:
    n = f = 0
    for sec in ("hook", "ugc_person", "product", "camera", "editing", "cta"):
        for k, v in a[sec].items():
            n += 1
            f += v not in (None, "", [], {})
    n += 1
    f += bool(a["structure"])
    return f / n
