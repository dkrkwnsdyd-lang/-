"""VIDEO STYLE PROFILES - 같은 상품도 스타일마다 컷 템포/카메라/전환/효과음/음악/자막 속도가 달라진다.

STANDARD 는 변화 없음(기존 동작). 값은 '재현 가능한 설정'이며 랜덤이 없다.
- tempo:      장면 길이 배율과 상·하한(초), Hook 상한, 음성 뒤 여유(pad)
- motion:     모션 선호 가감점(bias), 카메라 움직임 세기(intensity: 1.0=기본)
- transition: 장면 유형별 전환 (Hook 첫 장면은 항상 cut)
- sfx:        효과음이 붙는 장면 비율 상한, 강한 효과음(impact/riser/transition_hit) 허용 여부
- music:      mood, 템포(bpm), 킥 세기, 패드 세기, 음량
- caption:    자막 단어가 나오는 구간 배율 (작을수록 빠르게 팝)
"""
from __future__ import annotations

PROFILES: dict[str, dict] = {
    "STANDARD": {
        "label": "기본",
        "tempo": {"scale": 1.0, "min": 1.2, "max": 3.6, "hook_max": 2.4, "pad": 0.25},
        "motion": {"bias": {}, "intensity": 1.0},
        "transition": {},
        "sfx": {"ratio": 0.7, "heavy": True},
        "music": {"mood": "soft, warm, ~100 BPM", "bpm": 100, "kick": 0.8, "pad": 0.22, "gain": 0.35},
        "caption": {"span": 1.0},
    },
    "FAST_COMMERCE": {
        "label": "빠른 상품형",
        "tempo": {"scale": 0.82, "min": 1.1, "max": 2.6, "hook_max": 1.7, "pad": 0.12},
        "motion": {"bias": {"punch_in": 2.5, "zoom_in": 1.5, "shake": 1.0, "object_focus": 1.0, "light_sweep": 1.0,
                            "slow_zoom": -2.0, "ken_burns": -1.5, "floating_product": -1.0},
                   "intensity": 1.35},
        "transition": {"PRODUCT_REVEAL": "whip", "FEATURE": "whip", "DEMO": "cut", "BENEFIT": "cut", "PROBLEM": "cut", "PROOF": "cut", "CTA": "flash"},
        "sfx": {"ratio": 0.8, "heavy": True},
        "music": {"mood": "energetic, tight drums, ~124 BPM", "bpm": 124, "kick": 1.0, "pad": 0.16, "gain": 0.38},
        "caption": {"span": 0.6},
    },
    "STORY_AD": {
        "label": "스토리 광고형",
        "tempo": {"scale": 1.2, "min": 1.6, "max": 4.2, "hook_max": 2.8, "pad": 0.45},
        "motion": {"bias": {"slow_zoom": 2.5, "zoom_out": 2.0, "mask_reveal": 2.0, "light_sweep": 1.5, "floating_product": 1.5, "parallax": 1.5,
                            "punch_in": -3.0, "shake": -1.5, "zoom_in": -1.0},
                   "intensity": 0.8},
        "transition": {"PRODUCT_REVEAL": "soft", "PROBLEM": "soft", "FEATURE": "cut", "DEMO": "soft", "BENEFIT": "soft", "PROOF": "soft", "CTA": "soft"},
        "sfx": {"ratio": 0.5, "heavy": False},
        "music": {"mood": "cinematic, gentle build, ~84 BPM", "bpm": 84, "kick": 0.35, "pad": 0.32, "gain": 0.34},
        "caption": {"span": 0.9},
    },
    "UGC_REVIEW": {
        "label": "사용 후기형",
        "tempo": {"scale": 1.0, "min": 1.3, "max": 3.4, "hook_max": 2.2, "pad": 0.3},
        "motion": {"bias": {"ken_burns": 3.5, "pan_left": 3.0, "pan_right": 3.0, "slow_zoom": 2.0, "shake": 0.0,
                            "punch_in": -4.0, "mask_reveal": -4.0, "floating_product": -3.0, "parallax": -2.5, "light_sweep": -3.0, "zoom_in": -1.5},
                   "intensity": 1.0},
        "transition": {"PRODUCT_REVEAL": "cut", "FEATURE": "cut", "DEMO": "cut", "BENEFIT": "cut", "PROBLEM": "cut", "PROOF": "cut", "CTA": "soft"},   # 편집 느낌 없이 자연스러운 컷, 마지막만 부드럽게
        "sfx": {"ratio": 0.3, "heavy": False},
        "music": {"mood": "light acoustic, natural, ~92 BPM", "bpm": 92, "kick": 0.0, "pad": 0.2, "gain": 0.22},
        "caption": {"span": 0.8},
    },
}


def profile(style: str | None) -> dict:
    return PROFILES.get(style or "STANDARD", PROFILES["STANDARD"])


def apply_tempo(scenes: list, style: str, floor: float = 0.0) -> None:
    """장면 길이를 스타일 템포로 조정 (Hook 은 상한, 나머지는 배율 후 상·하한)."""
    t = profile(style)["tempo"]
    if t["scale"] == 1.0:
        return
    for i, s in enumerate(scenes):
        d = s.duration * t["scale"]
        if s.scene_type == "HOOK":
            d = min(d, t["hook_max"])
        s.duration = round(max(t["min"], min(t["max"], d)), 2)
    total = sum(s.duration for s in scenes)
    if floor and total < floor:                         # 12~15초 같은 목표 길이 하한은 스타일이 깨지 않는다
        k = floor / total
        for s in scenes:
            s.duration = round(min(t["max"] + 0.9, s.duration * k), 2)     # 하한을 지키기 위해서만 상한을 넘긴다


def apply_transitions(scenes: list, style: str) -> None:
    tr = profile(style)["transition"]
    if not tr:
        return
    for i, s in enumerate(scenes):
        s.transition = "cut" if i == 0 else tr.get(s.scene_type, s.transition)
