"""MOTION DIRECTOR - 장면의 의미(대사/목적/상품 특징)를 읽고 모션을 고른다. 랜덤 적용 금지.

선택 근거는 세 가지다.
1) 장면 목적: HOOK 은 시선을 끄는 모션, CTA 는 안정적인 모션 ...
2) 대사/자막의 의미 신호: 의문 -> mask_reveal, 상품 특징어 -> object_focus, 거치/고정 -> pan, 빛/컬러 -> light_sweep ...
3) 레이아웃과의 호환: 배경/제품이 분리된 카드 레이아웃에서만 parallax/depth_zoom/floating_product

같은 입력이면 같은 결과. 선택 이유는 decisions['motion'] 에 기록해 Preview 에서 사용자가 볼 수 있다.
"""
from __future__ import annotations

import math
import re

MOTIONS = ["zoom_in", "zoom_out", "slow_zoom", "pan_left", "pan_right", "parallax", "depth_zoom", "mask_reveal", "object_focus",
           "background_blur", "light_sweep", "floating_product", "punch_in", "shake", "ken_burns"]
ZOOM_FAMILY = {"zoom_in", "zoom_out", "slow_zoom", "punch_in", "depth_zoom", "ken_burns", "object_focus"}
LABELS = {"zoom_in": "줌 인", "zoom_out": "줌 아웃", "slow_zoom": "느린 줌", "pan_left": "왼쪽 패닝", "pan_right": "오른쪽 패닝",
          "parallax": "패럴랙스", "depth_zoom": "깊이 줌", "mask_reveal": "마스크 공개", "object_focus": "대상 집중",
          "background_blur": "배경 블러", "light_sweep": "빛 스윕", "floating_product": "떠 있는 상품", "punch_in": "펀치 인",
          "shake": "흔들림", "ken_burns": "켄 번즈"}
CAMERA_TEXT = {"zoom_in": "slow dolly-in", "zoom_out": "pull-back reveal", "slow_zoom": "very slow push-in", "pan_left": "lateral slide left",
               "pan_right": "lateral slide right", "parallax": "parallax slide (background counter-moves)",
               "depth_zoom": "depth push (background approaches faster)", "mask_reveal": "circular mask reveal",
               "object_focus": "focus pull onto the subject", "background_blur": "background defocus", "light_sweep": "light sweep across surface",
               "floating_product": "gentle levitation", "punch_in": "fast punch zoom", "shake": "short impact shake", "ken_burns": "slow drift zoom"}

# 배경/제품이 분리되는 레이아웃 (패럴랙스 계열 허용)
LAYERED = {"product_center", "floating_product", "result", "cta"}
CARD_LIKE = LAYERED | {"product_overlay", "text_focus"}
ALLOWED: dict[str, set] = {
    "review_quote": {"slow_zoom", "light_sweep"}, "comparison": {"slow_zoom", "light_sweep"},
    "three_benefits": {"slow_zoom", "background_blur", "light_sweep", "zoom_in"},
    "before_after": {"slow_zoom", "zoom_in"},
    "split_screen": {"pan_left", "pan_right", "slow_zoom", "ken_burns", "zoom_in"},
    "problem_solution": {"zoom_out", "slow_zoom", "shake", "object_focus"},
    "feature_callout": {"object_focus", "zoom_in", "slow_zoom"},
    "floating_product": {"floating_product", "slow_zoom", "light_sweep", "depth_zoom", "parallax"},
    "product_overlay": {"slow_zoom", "zoom_in", "pan_left", "pan_right", "light_sweep", "background_blur", "ken_burns"},
    "text_focus": {"slow_zoom", "zoom_in", "background_blur", "light_sweep"},
}
GENERAL = set(MOTIONS) - {"parallax", "depth_zoom", "floating_product"}
CARD = set(MOTIONS) - {"pan_left", "pan_right"}


def allowed_for(layout: str) -> set:
    if layout in ALLOWED:
        return ALLOWED[layout]
    return CARD if layout in LAYERED else GENERAL


# 장면 유형별 기본 선호 (0~6)
BASE = {
    "HOOK": {"punch_in": 6, "mask_reveal": 5, "zoom_in": 4, "shake": 3, "object_focus": 3},
    "PROBLEM": {"zoom_out": 5, "shake": 4, "slow_zoom": 3, "object_focus": 2},
    "PRODUCT_REVEAL": {"zoom_in": 5, "punch_in": 4, "mask_reveal": 4, "floating_product": 4, "parallax": 3, "light_sweep": 3},
    "FEATURE": {"object_focus": 6, "depth_zoom": 4, "zoom_in": 4, "pan_right": 3, "pan_left": 3, "light_sweep": 3},
    "DEMO": {"ken_burns": 5, "pan_right": 5, "pan_left": 5, "slow_zoom": 4, "zoom_in": 3},
    "BENEFIT": {"slow_zoom": 5, "light_sweep": 5, "floating_product": 4, "parallax": 3, "zoom_out": 3},
    "PROOF": {"slow_zoom": 5, "light_sweep": 3},
    "CTA": {"floating_product": 5, "light_sweep": 4, "slow_zoom": 4, "zoom_in": 2},
}
# 대사/자막에서 읽는 의미 신호 -> (모션, 가점, 이유)
SIGNALS = [
    (r"\?|뭘까|궁금|비밀|정체|아직", "mask_reveal", 4, "의문/궁금증 → 가려졌다 드러나는 공개"),
    (r"바로 이|정답|이게|이거|짠|드디어", "punch_in", 3, "제품을 짚는 순간 → 빠른 펀치"),
    (r"거치|고정|클립|끼우|꽂|연결|부착|장착|잡아|올려", "pan_right", 3, "'붙이고/고정'하는 동작 → 옆으로 훑는 패닝"),
    (r"LED|빛|컬러|색|조명|반짝|밝|링(?!크)|광(?!고)", "light_sweep", 3, "빛/색을 말함 → 빛이 훑고 지나감"),
    (r"큰|넓|대용량|크기|사이즈", "zoom_out", 3, "크기/규모를 말함 → 물러나서 전체를 보여줌"),
    (r"작|슬림|미니|가벼|얇", "zoom_in", 2, "작음/슬림 → 가까이 보여줌"),
    (r"완성|결과|모습|깔끔|한눈|이런 느낌", "slow_zoom", 3, "결과/모습 → 천천히 머무르며 보여줌"),
    (r"불편|번거|스트레스|힘들|실패|문제|걱정", "shake", 3, "불편/문제 → 짧은 흔들림으로 긴장"),
    (r"디테일|가까이|자세히|꼼꼼|마감|질감", "depth_zoom", 3, "디테일을 말함 → 깊이 있게 다가감"),
]


def _text(scene) -> str:
    return " ".join([scene.narration or "", scene.main_caption or "", scene.sub_caption or ""])


def _score(motion: str, scene, features: list[str], prev: str | None, counts: dict, zoom_ratio: float, idx: int) -> tuple[float, list[str]]:
    why: list[str] = []
    s = float(BASE.get(scene.scene_type, {}).get(motion, 0.5))
    txt = _text(scene)
    for pat, mo, w, reason in SIGNALS:
        if re.search(pat, txt) and (mo == motion or (mo == "pan_right" and motion == "pan_left")):
            s += w if motion == mo else w - 0.5
            if reason not in why:
                why.append(reason)
    mention = [f for f in features if f and any(tok in txt for tok in re.findall(r"[0-9A-Za-z가-힣\-]{2,}", f))]
    if mention and motion == "object_focus":
        s += 7 if scene.scene_type in ("FEATURE", "DEMO") else 4      # 특징을 말하는 순간 해당 영역 강조 (지시서 품질 규칙)
        why.insert(0, f"상품 특징 '{mention[0]}' 을 말하는 순간 해당 부분을 강조")
    if scene.layout == "feature_callout" and motion == "object_focus":
        s += 2
    if motion == prev:
        s -= 100                                     # 연속 같은 모션 금지
    s -= 2.0 * counts.get(motion, 0)                 # 반복 억제
    if motion in ZOOM_FAMILY and zoom_ratio > 0.55:
        s -= 3.0                                     # 전부 줌 금지
    if motion in ("pan_left", "pan_right"):
        s += 0.2 if (motion == "pan_right") == (idx % 2 == 0) else 0.0   # 좌우를 번갈아 (결정적)
    return s, why


def select_motions(scenes: list, features: list[str], bias: dict | None = None) -> None:
    """scenes[i].image_motion / camera_motion / decisions['motion'] 을 채운다."""
    prev: str | None = None
    counts: dict[str, int] = {}
    n = len(scenes)
    zoomish = 0
    for i, sc in enumerate(scenes):
        allowed = allowed_for(sc.layout)
        zr = zoomish / max(i, 1)
        cands = []
        for m in MOTIONS:
            if m not in allowed:
                continue
            s, why = _score(m, sc, features, prev, counts, zr, i)
            if bias and m in bias:
                s += bias[m]                               # 영상 스타일 선호 (같은 입력/스타일이면 같은 결과)
                if abs(bias[m]) >= 2 and bias[m] > 0 and not why:
                    why = ["영상 스타일에 맞는 카메라"]
            cands.append((s, -MOTIONS.index(m), m, why))
        cands.sort(reverse=True)
        best = cands[0]
        pick = best[2]
        if best[0] < -50:                            # 후보가 전부 직전과 같다면 허용 집합 밖 안전 모션
            pick = next((m for m in ("slow_zoom", "zoom_in", "light_sweep") if m != prev), "slow_zoom")
            best = (0.0, 0, pick, ["허용 모션이 직전과 겹쳐 안전 모션 사용"])
        sc.image_motion = pick
        sc.camera_motion = CAMERA_TEXT[pick]
        reason = best[3][0] if best[3] else f"{sc.scene_type} 장면의 기본 선호"
        sc.decisions["motion"] = f"{LABELS[pick]} ({best[0]:.1f}점) - {reason} / 후보: " + ", ".join(f"{LABELS[c[2]]} {c[0]:.1f}" for c in cands[1:3])
        counts[pick] = counts.get(pick, 0) + 1
        zoomish += 1 if pick in ZOOM_FAMILY else 0
        prev = pick
    _ensure_not_all_zoom(scenes, features)


def _ensure_not_all_zoom(scenes: list, features: list[str]) -> None:
    """모든 장면이 줌 계열이면 안 된다: 4장면 이상에서 줌 비율이 60% 를 넘으면 가장 약한 선택을 비줌 모션으로 교체."""
    n = len(scenes)
    if n < 4:
        return
    limit = math.floor(n * 0.6)
    zoom_idx = [i for i, s in enumerate(scenes) if s.image_motion in ZOOM_FAMILY]
    for i in reversed(zoom_idx):
        if len(zoom_idx) <= limit:
            break
        sc = scenes[i]
        prev = scenes[i - 1].image_motion if i else None
        nxt = scenes[i + 1].image_motion if i + 1 < n else None
        alts = [m for m in allowed_for(sc.layout) if m not in ZOOM_FAMILY and m not in (prev, nxt)]
        if alts:
            alt = sorted(alts, key=lambda m: -BASE.get(sc.scene_type, {}).get(m, 0))[0]
            sc.decisions["motion"] = sc.decisions.get("motion", "") + f" → 줌 계열 과다로 {LABELS[alt]} 로 교체"
            sc.image_motion, sc.camera_motion = alt, CAMERA_TEXT[alt]
            zoom_idx.remove(i)
