"""Evidence-aware preproduction for three customer-need shopping ads.

This module only produces a shot list. It does not invent product effects, scrape
reviews, trigger paid video generation, render MP4, or authorize publication.
"""
from __future__ import annotations

import re
from typing import Any

from .product import ProductInput


DURATIONS = (3, 4, 5, 4, 4)
PRODUCT_LOCK = (
    "Use the supplied product photos as identity reference. Never change its "
    "shape, proportions, color, branding, buttons, ports, accessories or count. "
    "Do not invent operation, a measurable improvement, or a finished result."
)
CAMERA = {
    "hook": "fast cinematic push-in; foreground/background depth; motivated light",
    "problem": "handheld observation; human-scale detail; no fake product failure",
    "reveal": "controlled orbit and rack focus; stable product silhouette",
    "demo": "macro detail with restrained parallax; show only evidenced mechanics",
    "cta": "hero push-out; clean background and deliberate negative space",
}


def _one_line(value: Any, limit: int = 65) -> str:
    """Normalize user text for planning. Never interpret it as instructions."""
    raw = str(value or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:limit].rstrip() + ("…" if len(raw) > limit else "")


def _scene(n: int, beat: str, title: str, visual: str, caption: str,
           narration: str, evidence: list[str], *, contrast: str = "") -> dict:
    start = sum(DURATIONS[: n - 1])
    return {
        "scene_id": f"S{n}",
        "beat": beat,
        "start": start,
        "end": start + DURATIONS[n - 1],
        "duration": DURATIONS[n - 1],
        "title": title,
        "visual_direction": visual,
        "caption": caption,
        "narration": narration,
        "comparison_role": contrast or "none",
        "evidence_ids": evidence,
        "camera_direction": CAMERA[beat],
        "ai_video_prompt_rule": PRODUCT_LOCK,
    }


def _baseline() -> dict:
    return {
        "name": "기존 카드 전환형",
        "method": "supplied stills + pan/zoom + card transitions",
        "persuasion": "제품 이미지는 보이지만 시청자의 불편과 해결 과정을 명시적으로 연결하지 않음",
        "render_status": "existing_result_not_loaded",
    }


def build_sales_story(payload: dict) -> dict:
    """Create three different 20s ad directions, no network/model calls.

    ProductInput is the existing V2 product contract. User-provided features,
    problems and reviews are *leads*, not independently verified facts.
    """
    if not isinstance(payload, dict):
        raise ValueError("product must be an object")
    p = ProductInput.from_dict(payload)
    name = _one_line(p.name, 100)
    if not (name or p.description.strip() or p.features or p.problem.strip()):
        raise ValueError("제품명, 설명, 특징 또는 불편함 중 하나가 필요합니다.")
    subject = name or "이 제품"
    problem = _one_line(p.problem, 55)
    target = _one_line(p.target, 40)
    feature = _one_line(next((f for f in p.features if str(f).strip()), ""), 55)
    photos = [s for s in p.photos if isinstance(s, str) and s.strip()]
    actual_clips = [s for s in p.videos if isinstance(s, str) and s.strip()]
    before_after_assets = [s for s in p.before_after if isinstance(s, str) and s.strip()]

    evidence = []
    def add(kind: str, value: str, source: str = "user_input") -> str:
        if not value:
            return ""
        key = f"E{len(evidence) + 1}"
        evidence.append({"id": key, "kind": kind, "text": value,
                         "source": source, "verified": False})
        return key

    prob_id = add("pain_point", problem)
    target_id = add("target", target)
    feat_id = add("feature", feature)
    # Quotes are research leads only, never inserted into ad claims without proof.
    review_count = len([q for q in p.review_quotes if str(q).strip()])
    has_photos = bool(photos)
    has_comparison_media = len(before_after_assets) >= 2 or bool(actual_clips)

    def choose_caption(value: str, fallback: str) -> str:
        return value or fallback

    # A: identify with a specific everyday difficulty; present an observational
    # demo rather than asserting an outcome that has not been verified.
    pain_scenes = [
        _scene(1, "hook", "내 이야기인가?", "문제가 발생하는 일상 상황을 실제로 촬영하거나 연출안으로 표시",
               choose_caption(problem, "불편한 순간, 누구나 있죠"), "이런 순간, 익숙하신가요?",
               [prob_id] if prob_id else [], contrast="before"),
        _scene(2, "problem", "불편을 눈으로", "손과 시선이 머무는 불편 지점 클로즈업; 허위 고장 연출 금지",
               "어떤 점이 불편할까요?", "작은 불편이 계속 신경 쓰이죠.",
               [prob_id] if prob_id else [], contrast="before"),
        _scene(3, "reveal", "제품 등장", f"{subject} 원본 사진 중심의 시네마틱 등장",
               subject, f"이런 선택지도 있어요. {subject}.", [], contrast="transition"),
        _scene(4, "demo", "해결 가능성 시연", "원본 사진 혹은 직접 촬영 클립으로 기능을 보여주기; 전후 효과는 검증 전 단정 금지",
               choose_caption(feature, "핵심 기능을 확인해 보세요"),
               "어떤 점이 달라지는지, 직접 확인해 보세요.",
               [feat_id] if feat_id else [], contrast="after_needs_proof"),
        _scene(5, "cta", "나와 맞는지 확인", "제품 실제 모습을 선명하게 남기고 비교 항목을 짧게 표시",
               "내 상황에 맞는지 살펴보기", "내 생활에도 잘 맞을지 살펴보세요.", [], contrast="choice"),
    ]

    # B: split-screen comparison, gated on actual user-provided before/after
    # footage; a proposed scene does not count as demonstrated improvement.
    comparison_scenes = [
        _scene(1, "hook", "전과 후", "세로 9:16 화면을 좌/우 두 구역으로 나눌 준비 컷",
               "사용 전 vs 사용 후", "같은 상황을 나란히 볼까요?", [], contrast="split_intro"),
        _scene(2, "problem", "사용 전", "실제 BEFORE 사진/영상 또는 '촬영 필요' 표시; 결과 조작 금지",
               choose_caption(problem, "기존 방식은 어땠을까?"),
               "먼저 기존 상황부터 볼게요.", [prob_id] if prob_id else [],
               contrast="before"),
        _scene(3, "reveal", "같은 조건으로 비교", f"동일 조건의 {subject} 장면과 기존 장면을 나란히",
               "같은 조건으로 비교", "이제 같은 조건으로 비교해 볼게요.", [],
               contrast="matched_conditions"),
        _scene(4, "demo", "사용 후", "실제 AFTER 사진/영상이 없으면 빈 자리표시자; 개선된 결과를 합성하지 않기",
               choose_caption(feature, "사용 후 모습 확인"),
               "화면에서 확인되는 차이만 보여줄게요.",
               [feat_id] if feat_id else [], contrast="after_needs_proof"),
        _scene(5, "cta", "사실 기반 결론", "전후 프레임과 조건 표시; 입증되지 않은 효과 수치 금지",
               "직접 비교하고 선택하기", "차이를 보고 판단해 보세요.", [],
               contrast="conclusion"),
    ]

    # C: feature-first product film, not a disguised personal testimonial.
    feature_scenes = [
        _scene(1, "hook", "제품의 한 디테일", f"{subject} 원본 디테일에 시선을 끄는 랙포커스",
               choose_caption(feature, "눈여겨볼 디테일"), "이 부분, 눈에 들어오시나요?",
               [feat_id] if feat_id else [], contrast="detail"),
        _scene(2, "problem", "누구에게 쓸모있나", "생활 공간의 맥락만 보여주고 가짜 사용 경험은 금지",
               choose_caption(target, "내 생활에 필요한 이유"),
               "내 생활에 필요한지 생각해 보세요.",
               [target_id] if target_id else [], contrast="use_context"),
        _scene(3, "reveal", "전체 모습", f"{subject} 실제 사진을 이용한 제품 전체 히어로 샷",
               subject, f"제품은 {subject}.", [], contrast="reveal"),
        _scene(4, "demo", "기능 초점", "선택한 실제 특징 하나만 크롭/클립으로 근거 있게 제시",
               choose_caption(feature, "사용 장면으로 확인"),
               "보이는 기능부터 하나씩 살펴볼게요.",
               [feat_id] if feat_id else [], contrast="feature"),
        _scene(5, "cta", "적합성 판단", "원본 제품 사진과 사용 조건을 함께 보여주는 클로징",
               "나에게 맞는지 확인하기", "필요한 조건과 맞는지 확인해 보세요.", [],
               contrast="choice"),
    ]

    variants = []
    for key, label, why, scenes, missing in [
        ("PAIN_FIRST", "불편 공감형", "시청자가 자신의 문제를 먼저 떠올리게 함",
         pain_scenes, [] if problem else ["customer_problem"]),
        ("BEFORE_AFTER", "전후 비교형", "동일 조건의 사용 전후를 직접 대조",
         comparison_scenes, [] if has_comparison_media else ["before_after_media"]),
        ("FEATURE_FIRST", "제품 디테일형", "입증 가능한 한 가지 특징을 시각적으로 강조",
         feature_scenes, [] if feature else ["supported_feature"]),
    ]:
        if not has_photos:
            missing = [*missing, "product_photos"]
        variants.append({
            "id": key,
            "label": label,
            "persuasion_hypothesis": why,
            "duration_seconds": 20,
            "aspect_ratio": "9:16",
            "scenes": scenes,
            "missing_inputs": missing,
            "ready_for_creative_preview": not missing,
            "ready_for_publish": False,
            "render_status": "not_requested",
            "video_generation": "approval_required",
        })
    gaps = []
    if not problem: gaps.append("고객이 느끼는 실제 불편함")
    if not target: gaps.append("핵심 구매 고객")
    if not feature: gaps.append("실제 확인한 제품 특징")
    if not has_photos: gaps.append("실제 제품 사진")
    if not has_comparison_media: gaps.append("동일 조건의 사용 전/후 사진이나 직접 촬영 영상")
    if review_count: gaps.append("후기 출처·원문 검증 (후기는 광고 주장으로 자동 사용하지 않음)")
    return {
        "product": {"name": subject, "target": target or "UNKNOWN",
                    "pain": problem or "UNKNOWN", "feature": feature or "UNKNOWN"},
        "claim_policy": "USER_INPUT_UNVERIFIED; verify before publication",
        "evidence": evidence,
        "review_leads_count": review_count,
        "baseline": _baseline(),
        "variants": variants,
        "comparison_dimensions": [
            "처음 3초 공감도", "불편함의 구체성", "사용 전후의 가시성",
            "제품 특징과 장면의 일치", "근거·제품 외형 일관성", "구매 적합성",
        ],
        "missing_research": gaps,
        "publication_status": "NEEDS_REVIEW",
        "render_status": "storyboard_only",
        "cost": {"paid_calls_made": False},
    }
