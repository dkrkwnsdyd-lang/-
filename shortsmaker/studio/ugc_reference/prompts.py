"""Video Prompt Generator + Prompt Package.

Scene 마다 독립적인 영상 생성 프롬프트(영어, 행동/카메라 구체적)를 만든다. Video Prompt 에는 내레이션/자막/광고 카피/CTA 를 넣지 않는다 (별도 필드로 분리 관리).
특정 영상 서비스(Higgsfield/Seedance/Veo 등)에 종속되지 않는 일반 JSON 패키지다. 어댑터는 이 패키지를 각 서비스 형식으로 바꿔 쓴다.
상품 외형은 사용자가 올린 실제 상품 사진을 기준 이미지로 삼아 그대로 유지해야 한다 (product_reference 제약).
"""
from __future__ import annotations

import json
import re

CATEGORY_ENV = {"kitchen": "a tidy home kitchen counter", "fitness": "a bright living room after a workout", "camping": "a campsite at dusk with natural light",
                "beauty": "a bathroom vanity with soft window light", "living": "a lived-in living room", "electronics": "a home desk by a window", "general": "an everyday home setting"}
LIGHT = {"camping": "warm ambient evening light", "beauty": "soft natural window light"}
EXPR = {"hook": "curious, slightly surprised", "problem": "mildly annoyed, relatable", "agitation": "tired, sighing", "solution": "relieved, a small smile",
        "demonstration": "focused, interested", "proof": "calm, matter-of-fact", "benefit": "satisfied, relaxed", "cta": "friendly, direct to camera"}
SHOT_EN = {"extreme_close_up": "extreme close-up", "close_up": "close-up", "medium": "medium shot", "wide": "wide shot"}
MOVE_EN = {"handheld": "handheld smartphone movement with slight natural shake", "zoom": "slow digital zoom in", "push_in": "slow push-in", "pan": "slow pan",
           "tilt": "gentle tilt", "static": "locked-off static frame"}
ANGLE_EN = {"eye_level": "eye-level angle", "high": "slightly high angle", "low": "slightly low angle", "top_down": "top-down angle", "pov": "first-person POV angle"}
PERSON_EN = {"hands_only": "only a person's hands are visible (no face)", "pov": "first-person POV, the user's hands and forearms visible", "talking_head": "a person speaking casually to the camera",
             "selfie": "a person filming themselves with a smartphone"}
_KO = re.compile(r"[가-힣]")


def _en_or_generic(text: str, fallback: str) -> str:
    """프롬프트는 영어로: 한국어 문장은 영상 모델에 그대로 넣지 않고 짧은 영어 설명으로 대체."""
    return fallback if _KO.search(text or "") else (text or fallback)


def scene_prompt(ctx, scene: dict, board: dict, category: str, feature_en: str = "") -> str:
    stage = scene["stage"]
    mode = board.get("person_mode") or "selfie"
    product = f"the product '{ctx.p.name}'" if ctx.p.name else "the product"
    action = {"hook": "starts the scene with the situation that makes people stop scrolling, product partly in frame",
              "problem": "shows the everyday annoyance the product is meant to address, product not yet fully visible",
              "agitation": "repeats the annoying moment once more with a tired reaction",
              "solution": "brings the product into frame for the first time and holds it clearly",
              "demonstration": f"operates the product to show its main feature{(' (' + feature_en + ')') if feature_en else ''}, in one continuous natural motion",
              "proof": "holds the product and shows it calmly to the camera",
              "benefit": "uses the product naturally and settles into a relaxed finish",
              "cta": "holds the product in front of the camera and gives a friendly final look"}[stage]
    person = PERSON_EN.get(mode, PERSON_EN["selfie"])
    parts = [
        f"Subject: {person}; {action}.",
        f"Product: {product}, identical to the reference image (same shape, proportions, color, logo, printed text, button positions); do not redesign or invent parts.",
        f"Location: {CATEGORY_ENV.get(category, CATEGORY_ENV['general'])}.",
        f"Person: an ordinary person, natural unstyled look, no celebrity or lookalike.",
        f"Expression: {EXPR[stage]}.",
        f"Camera: {SHOT_EN[scene['camera_shot']]}, {ANGLE_EN[scene['camera_angle']]}, {MOVE_EN[scene['camera_movement']]}.",
        f"Lighting/Environment: {LIGHT.get(category, 'soft natural daylight')}, slightly imperfect real-life background, no studio set.",
        "Style: authentic UGC smartphone footage feeling, vertical 9:16, 1080x1920, casual framing, realistic skin and materials.",
        f"Duration: {scene['duration']:.0f} seconds, single continuous shot.",
        "Constraints: no on-screen text, no subtitles, no logos or brand marks other than those on the real product, no extra products, no spoken dialogue audio.",
    ]
    return " ".join(parts)


def build_package(ctx, concept: dict, board: dict, category: str, product_reference: str | None = None) -> dict:
    """Prompt Package: 영상 생성 엔진에 넘길 수 있는 일반 JSON."""
    feats = [f for f in ctx.p.features if f]
    scenes = []
    for sc in board["scenes"]:
        feat_en = "" if any(_KO.search(f) for f in feats) else (feats[0] if feats else "")
        scenes.append({"scene_number": sc["scene_number"], "time": sc["time"], "duration": sc["duration"], "stage": sc["stage"],
                       "video_prompt": scene_prompt(ctx, sc, board, category, feat_en),
                       "voice_over": sc["voice_over"], "caption": sc["caption"], "sfx": sc["sfx"], "purpose": sc["purpose"]})
    return {"version": 1, "format": "shopshorts.ugc_prompt_package", "provider_agnostic": True,
            "concept": {"id": concept["id"], "type": concept["type"], "title": concept["title"], "hook": concept["hook"]["text"], "target": concept["target"],
                        "selling_angle": concept["selling_angle"], "emotion": concept["emotion"], "main_usp": concept["main_usp"], "ugc_kind": concept.get("ugc_kind", "")},
            "product_reference": {"image": product_reference, "name": ctx.p.name, "rule": "Keep the product identical to the reference image; reject outputs that change shape/color/logo/buttons."},
            "scenes": scenes, "voice_script": [s["voice_over"] for s in scenes], "captions": [s["caption"] for s in scenes],
            "cta": board["scenes"][-1]["voice_over"] if board["scenes"] else "", "music_mood": board.get("bgm") or "calm", "total_seconds": board["total_seconds"],
            "format_spec": {"aspect": "9:16", "resolution": "1080x1920", "audio": "voice/captions/sfx/bgm are produced separately; video prompts carry visuals only"}}


def check_separation(package: dict) -> list[str]:
    """Video Prompt 에 음성/자막/CTA 문구가 섞이지 않았는지 검사 (섞였으면 문제 목록)."""
    problems = []
    for sc in package["scenes"]:
        for field in ("voice_over", "caption"):
            text = re.sub(r"[\[\]]", "", sc[field]).strip()
            if len(text) >= 4 and text in sc["video_prompt"]:
                problems.append(f"Scene {sc['scene_number']}: video_prompt 에 {field} 문구가 섞여 있어요")
    return problems


def dumps(package: dict) -> str:
    return json.dumps(package, ensure_ascii=False, indent=2)
