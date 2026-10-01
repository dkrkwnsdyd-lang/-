"""SOUND EFFECT DIRECTOR - 효과음은 장면 전환이나 강조 지점에만. 모든 장면에 넣지 않는다.

지원: whoosh, pop, click, impact, swipe, ding, riser, transition_hit, soft_hit
"""
from __future__ import annotations

SFX_CATALOG = ("whoosh", "pop", "click", "impact", "swipe", "ding", "riser", "transition_hit", "soft_hit")
HEAVY = {"impact", "transition_hit", "riser"}
MAX_SCENE_RATIO = 0.7      # 효과음이 붙는 장면 비율 상한


def _pick(scene, prev) -> list[dict]:
    t, tr = scene.scene_type, scene.transition
    out: list[dict] = []
    if t == "PRODUCT_REVEAL":
        out.append({"sfx": "whoosh" if tr == "whip" else "transition_hit", "at": "start", "gain": 0.55})
        out.append({"sfx": "impact", "at": "start", "gain": 0.5})
    elif t == "CTA":
        out.append({"sfx": "ding", "at": "start", "gain": 0.4})
    elif t == "BENEFIT":
        if scene.emphasis:
            out.append({"sfx": "ding", "at": "emphasis", "gain": 0.38})
    elif t == "DEMO":
        if scene.image_motion in ("pan_left", "pan_right"):
            out.append({"sfx": "swipe", "at": "start", "gain": 0.4})
        elif scene.emphasis:
            out.append({"sfx": "pop", "at": "emphasis", "gain": 0.42})
    elif t == "FEATURE":
        if scene.layout == "feature_callout":
            out.append({"sfx": "click", "at": "start", "gain": 0.4})
        elif scene.emphasis:
            out.append({"sfx": "pop", "at": "emphasis", "gain": 0.45})
    elif t == "PROBLEM":
        out.append({"sfx": "soft_hit", "at": "start", "gain": 0.35})
    elif t == "HOOK":
        if scene.emphasis:
            out.append({"sfx": "pop", "at": "emphasis", "gain": 0.45})
    return out


def direct_sfx(scenes: list) -> None:
    """scenes 에 sound_effect 를 채운다 (전환/강조 지점에만, 연속 강타 금지, 비율 상한)."""
    prev_heavy = False
    for i, s in enumerate(scenes):
        s.sound_effect = [e for e in _pick(s, scenes[i - 1] if i else None) if e["sfx"] in SFX_CATALOG]
        heavy_now = any(e["sfx"] in HEAVY for e in s.sound_effect)
        if heavy_now and prev_heavy:                  # 연속 장면에 강한 효과음 금지
            s.sound_effect = [e for e in s.sound_effect if e["sfx"] not in HEAVY]
            heavy_now = False
        prev_heavy = heavy_now
    # 비율 상한: 넘으면 강조(pop) 효과음부터 제거
    limit = max(1, int(len(scenes) * MAX_SCENE_RATIO))
    with_sfx = [s for s in scenes if s.sound_effect]
    for s in with_sfx[::-1]:
        if len(with_sfx) <= limit:
            break
        if all(e["at"] == "emphasis" for e in s.sound_effect):
            s.sound_effect = []
            with_sfx = [x for x in scenes if x.sound_effect]
