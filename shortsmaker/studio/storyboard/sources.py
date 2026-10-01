"""VISUAL SOURCE ROUTER - 장면별 이미지/영상 소스 우선순위.

1. 사용자 업로드 이미지/영상  2. 상품 URL 이미지  3. 상세페이지 이미지  4. 무료 B-roll  5. AI Image  6. AI Video

비싼 AI Video 를 전체에 쓰지 않는다: 위 1~4 로 해결되지 않는 '핵심 장면'(DEMO)에만, 그것도 provider 가 검증된 뒤에.
지금은 1번만 실제로 쓸 수 있고, 나머지는 '필요하지만 없음(gap)' 으로 기록해서 Preview 에서 사용자가 결정하게 한다.
"""
from __future__ import annotations

TIERS = [
    ("user_media", "사용자 업로드 이미지/영상"),
    ("url_image", "상품 URL 이미지"),
    ("detail_page_image", "상품 상세페이지 이미지"),
    ("free_broll", "무료 B-roll"),
    ("ai_image", "AI Image"),
    ("ai_video", "AI Video"),
]
# 현재 실제로 쓸 수 있는 단계 (Pexels/Pixabay 는 영상 제작에 미연결, AI Video 어댑터는 검증 전)
AVAILABLE = {"user_media"}
MAX_AI_VIDEO_SCENES = 2
NEEDS_USAGE = ("DEMO", "BENEFIT")


def hands_only_prompt(product_name: str, scene_type: str, features: list[str]) -> str:
    """사용 장면 생성용 프롬프트 (Hands Only: 얼굴/전신 없이 손과 제품만). 제품은 기준 이미지 그대로."""
    act = {"DEMO": "a hand demonstrating the product's main feature", "BENEFIT": "a hand using the product naturally, finished result in frame"}.get(
        scene_type, "a hand holding the product")
    feat = f" Visible feature to keep clear: {features[0]}." if features else ""
    return (f"Hands only POV close-up, no face, no full body. {act}.{feat} The product '{product_name}' must be IDENTICAL to the reference image: "
            "same shape, proportions, color, logo, printed text, button positions. Soft natural daylight, clean tabletop, 9:16, "
            "one slow camera movement only (gentle push-in), 5 seconds.")


def route_visual_source(scene_type: str, primary: str | None, identity, clip_paths: list[str], product_name: str,
                        features: list[str], ai_scenes_used: int = 0) -> dict:
    """{kind, path, tier, reason, gap?, visual_prompt?, ai_candidate?}"""
    usage = getattr(identity, "usage_reference", None)
    # DEMO/BENEFIT 은 사용 장면을 우선: 영상 클립 > 사용 사진 > 기본 사진
    if scene_type in NEEDS_USAGE and clip_paths:
        return {"kind": "user_video", "path": clip_paths[0], "tier": 1, "reason": "사용자가 올린 사용 장면 영상 우선"}
    if scene_type in NEEDS_USAGE and usage:
        return {"kind": "user_photo", "path": usage, "tier": 1, "reason": "사용 장면 사진 우선"}
    out = {"kind": "user_photo", "path": primary, "tier": 1, "reason": "사용자 업로드 사진"}
    if scene_type in NEEDS_USAGE:
        # 사용 장면이 없다: 1~4단계로 해결 불가 -> AI 영상 후보로만 기록 (핵심 장면 + 상한 + provider 검증 후)
        out["gap"] = "usage_scene_missing"
        out["visual_prompt"] = hands_only_prompt(product_name, scene_type, features)
        out["ai_candidate"] = scene_type == "DEMO" and ai_scenes_used < MAX_AI_VIDEO_SCENES
        out["blocked"] = ("AI 영상 provider 미검증 - 실제 호출하지 않고 원본 사진 모션으로 대체" if "ai_video" not in AVAILABLE else "")
        out["reason"] += " (사용 장면 없음 - 사진 모션으로 대체)"
    return out
