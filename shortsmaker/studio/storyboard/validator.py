"""STORYBOARD 품질 규칙 (슬라이드쇼/PPT 처럼 보이지 않게). 위반은 issues 로 기록하고, 안전하게 고칠 수 있는 것은 자동 수정한다.

규칙
1. 동일 이미지 장시간 고정 금지        2. 동일 Layout 연속 금지         3. 동일 Motion 연속 금지
4. 모든 Scene 동일 Zoom 금지           5. 자막만 바뀌는 슬라이드 금지   6. 상품이 항상 중앙인 구성 금지
7. 장면마다 시각 변화 필수             8. Hook 첫 2초 시각 변화 강화    9. 제품 특징을 말하는 순간 해당 영역 강조
10. CTA 전 별도 시각 변화              + 데이터 신뢰도: 입력에 없는 가격/후기/성능(C) 표시
"""
from __future__ import annotations

import math
import re

from . import motion_director as MD
from .layouts import FAMILY, OFF_CENTER

LONG_SAME_IMAGE = 4.0        # 같은 사진이 연속으로 이 시간 넘게 쓰이면 위반 (레이아웃/모션이 달라도 '같은 이미지')
HOOK_WEAK = {"slow_zoom", "light_sweep", "background_blur", "floating_product"}
FOCUS_OK = {"object_focus"}
FOCUS_LAYOUT_OK = {"feature_callout", "three_benefits"}


def _mentions_feature(scene, features: list[str]) -> str | None:
    txt = " ".join([scene.narration, scene.main_caption, scene.sub_caption])
    for f in features:
        toks = [t for t in re.findall(r"[0-9A-Za-z가-힣\-]{2,}", f) if len(t) >= 2]
        if toks and any(t in txt for t in toks):
            return f
    return None


def validate(scenes: list, features: list[str], fix: bool = True) -> list[dict]:
    """[{rule, scene_id, message, fixed}] 반환. fix=True 면 안전한 항목은 고친다."""
    issues: list[dict] = []

    def add(rule: str, sid: str, msg: str, fixed: bool = False) -> None:
        issues.append({"rule": rule, "scene_id": sid, "message": msg, "fixed": fixed})

    n = len(scenes)
    for i, s in enumerate(scenes):
        prev = scenes[i - 1] if i else None
        if prev is not None:
            if s.layout == prev.layout:
                add("layout_repeat", s.scene_id, f"{prev.scene_id} 와 같은 레이아웃({s.layout}) 연속")
            if s.image_motion == prev.image_motion:
                add("motion_repeat", s.scene_id, f"{prev.scene_id} 와 같은 모션({s.image_motion}) 연속")
            same_src = s.visual_source.get("path") == prev.visual_source.get("path")
            if not (s.layout != prev.layout or s.image_motion != prev.image_motion or not same_src):
                add("no_visual_change", s.scene_id, "이전 장면과 화면 구성/모션/소스가 모두 같아 자막만 바뀜")
    # 같은 이미지 장시간 고정: 연속 구간의 같은 소스 누적 시간
    run_path, run_start = None, 0.0
    t = 0.0
    for s in scenes:
        path = s.visual_source.get("path")
        if path != run_path:
            run_path, run_start = path, t
        t += s.duration
        if t - run_start > LONG_SAME_IMAGE and path:
            add("same_image_long", s.scene_id, f"같은 사진이 {t - run_start:.1f}초 연속 사용됨 (> {LONG_SAME_IMAGE}s)")
            run_start = t - s.duration                       # 같은 구간을 반복 보고하지 않음
    # 모든 장면 줌 / 슬라이드쇼
    if n >= 4:
        zr = sum(1 for s in scenes if s.image_motion in MD.ZOOM_FAMILY) / n
        if zr > 0.6:
            add("all_zoom", scenes[0].scene_id, f"줌 계열 모션이 {zr:.0%}")
        most = max((sum(1 for s in scenes if s.visual_source.get("path") == p) for p in {s.visual_source.get("path") for s in scenes}), default=0)
        if most / n > 0.7 and len({s.layout for s in scenes}) < 3:
            add("slideshow", scenes[0].scene_id, "같은 사진 + 비슷한 레이아웃 위주 = 슬라이드쇼처럼 보임")
        off = sum(1 for s in scenes if s.layout in OFF_CENTER)
        if off < math.ceil(n / 3):
            add("always_centered", scenes[0].scene_id, f"비중앙 구도 {off}개 (최소 {math.ceil(n / 3)}개)")
    # Hook 첫 2초 시각 변화
    if scenes and scenes[0].scene_type == "HOOK" and scenes[0].image_motion in HOOK_WEAK:
        h = scenes[0]
        ok = [m for m in ("punch_in", "mask_reveal", "zoom_in") if m in MD.allowed_for(h.layout) and m != (scenes[1].image_motion if n > 1 else None)]
        if fix and ok:
            old = h.image_motion
            h.image_motion, h.camera_motion = ok[0], MD.CAMERA_TEXT[ok[0]]
            h.decisions["motion"] = h.decisions.get("motion", "") + f" → Hook 첫 2초 시각 변화 강화로 {MD.LABELS[ok[0]]} 로 교체 (원래 {MD.LABELS[old]})"
            add("hook_weak", h.scene_id, f"Hook 모션 {old} 가 약함", fixed=True)
        else:
            add("hook_weak", h.scene_id, f"Hook 모션 {h.image_motion} 가 약함")
    # 제품 특징을 말하는 순간 해당 영역 강조
    for i, s in enumerate(scenes):
        f = _mentions_feature(s, features) if s.scene_type in ("FEATURE", "DEMO") else None
        if f and s.image_motion not in FOCUS_OK and s.layout not in FOCUS_LAYOUT_OK:
            prev_m = scenes[i - 1].image_motion if i else None
            nxt_m = scenes[i + 1].image_motion if i + 1 < n else None
            if fix and "object_focus" in MD.allowed_for(s.layout) and "object_focus" not in (prev_m, nxt_m):
                s.image_motion, s.camera_motion = "object_focus", MD.CAMERA_TEXT["object_focus"]
                s.decisions["motion"] = s.decisions.get("motion", "") + f" → 특징 '{f}' 강조를 위해 대상 집중으로 교체"
                add("feature_not_emphasized", s.scene_id, f"특징 '{f}' 를 말하는데 강조 없음", fixed=True)
            else:
                add("feature_not_emphasized", s.scene_id, f"특징 '{f}' 를 말하는데 해당 영역 강조 없음")
    # CTA 전 별도 시각 변화
    if n >= 2 and scenes[-1].scene_type == "CTA":
        cta, before = scenes[-1], scenes[-2]
        if FAMILY.get(before.layout) == FAMILY.get(cta.layout):
            add("pre_cta_no_change", before.scene_id, f"CTA 직전 장면이 CTA 와 같은 계열({FAMILY.get(cta.layout)})")
        if cta.transition == "cut":
            add("cta_no_transition", cta.scene_id, "CTA 에 별도 전환 없음")
    # 데이터 신뢰도
    for s in scenes:
        if s.reliability == "C":
            add("unverified_claim", s.scene_id, "입력에 없는 데이터성 표현 포함: " + ", ".join(c["text"] for c in s.claims if c["reliability"] == "C"))
    return issues
