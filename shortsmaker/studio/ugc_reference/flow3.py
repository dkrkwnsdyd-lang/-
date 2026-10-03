"""3-Scene Flow Mode: AI_PRODUCT_UGC 안의 선택 기능 (기본 OFF).

Scene 1(Scroll Stopper/Hook) → Scene 2(Product Demo/Hero Use) → Scene 3(Result/Hero Shot/CTA) 한 흐름의 광고를 만들고,
장면마다 Google Flow(또는 다른 영상 생성 도구)에 그대로 복사해 넣을 수 있는 '완성형' 영어 프롬프트를 낸다.

원칙
- 새 시스템이 아니라 기존 구조 재사용: 대사/자막은 UGC Storyboard 의 문장 생성 + 사실 검증(line_issues), 연출은 UGC Reference Mixer 결과(있으면), 상품 외형은 Product Lock.
- 영상 프롬프트(flow_prompt)에는 한국어 대사/자막/상품명을 넣지 않는다. Voice Over / Caption / SFX 는 별도 필드로 관리.
- 입력에 없는 가격/할인/품절/판매량/후기/사용 경험은 만들지 않는다. 확인되지 않은 작동 방식은 시연하지 않고, 잡고/돌려 보여주는 동작까지만 쓴다.
- 레퍼런스에서는 Hook 방식/카메라/손동작/공개 타이밍/컷 속도/인물 방식/CTA 구조 같은 추상 패턴만 쓴다 (대사/자막/인물/로고/고유 장면 순서 복제 없음).
"""
from __future__ import annotations

import re

from ..strategy.common import line_issues, make_caption, strip_marks
from . import prompts
from .storyboard import _lines, _person_phrase, _safe

KEYWORDS = ["/tiktokcommercial", "/viralproductvideo", "/attentiongrabbing", "/stronghook", "/fastpaced", "/dynamicframing", "/scrollstopper", "/heroshot", "/ctaending"]
_KO = re.compile(r"[가-힣]")
DURATIONS = (3.0, 5.0, 5.0)

HAND = {"hook": "right hand", "demo": "right hand holds the product while the left index finger and thumb operate it", "result": "right hand"}
PERSON_FACE = {"selfie": "a person filming themselves with a smartphone, face partly visible",
               "pov": "first-person POV: only the user's hands and forearms are visible",
               "hands_only": "only a person's hands and forearms are visible (no face)",
               "talking_head": "a person speaking casually to the camera, upper body visible"}
LOCATION = dict(prompts.CATEGORY_ENV)
LIGHT = {"camping": "warm ambient evening light", "beauty": "soft natural window light"}

PRODUCT_LOCK = [
    "Product Lock: the product must be IDENTICAL to the attached reference photo in every frame (shape, proportions, color, finish, logo, printed text, button positions, parts).",
    "Keep the product at a believable real-world size relative to the hand; never enlarge, shrink, redesign, recolor or add parts.",
    "Show only functions that are stated in the product facts; if the way it works is not given, only hold, turn and present the product, do not invent how it operates.",
    "Hands must look natural: five fingers per hand, no merged or extra fingers, no fingers or hand passing through the product, the product is never duplicated or morphs between frames.",
]
NEGATIVE = ["extra or deformed fingers", "hand or fingers passing through the product", "duplicated or multiple products", "product changing shape, color or logo between frames",
            "invented buttons, ports or parts", "on-screen text, subtitles, captions or watermarks", "brand logos other than those printed on the real product",
            "celebrity or lookalike faces", "studio commercial lighting or glossy ad look", "distorted or unreadable product text", "spoken dialogue in the audio"]


def _hook_style(ctx, mixed: dict | None) -> tuple[str, str]:
    """(스타일, 이유). 상품에 맞는 방식만: problem(불편 입력 있음) / result_first(특징 입력 있음) / curiosity / unexpected."""
    pat = (((mixed or {}).get("aspects") or {}).get("hook") or {}).get("pattern") or {}
    ref = pat.get("pattern") or ""
    has_prob, has_feat = bool(ctx.p.problem.strip()), any(f.strip() for f in ctx.p.features)
    if ref in ("problem_first", "empathy") and has_prob:
        return "problem", "레퍼런스 Hook(문제 제기)이 입력된 불편과 맞아 채택"
    if ref in ("result_first", "demo_first") and has_feat:
        return "result_first", "레퍼런스 Hook(결과/시연 선공개)이 입력된 특징과 맞아 채택"
    if ref in ("curiosity_gap", "question", "shock_visual"):
        return "curiosity", "레퍼런스 Hook(궁금증)을 채택 (상품 정보와 충돌 없음)"
    if has_prob:
        return "problem", "입력에 해결하는 불편이 있어 문제 상황으로 시작"
    if has_feat:
        return "curiosity", "입력된 특징 일부만 먼저 보여 궁금증을 만든다"
    return "unexpected", "입력된 정보가 적어 제품이 예상 밖으로 등장하는 방식 (효과를 주장하지 않음)"


def _pat(mixed: dict | None, aspect: str) -> dict:
    return (((mixed or {}).get("aspects") or {}).get(aspect) or {}).get("pattern") or {}


def _feature_en(ctx, feature_en: list[str] | None) -> str:
    """영어 특징 구절: 입력이 영어이거나 번역본이 주어졌을 때만. 없으면 '' (프롬프트에 한국어를 넣지 않는다)."""
    for f in (feature_en or []):
        if f and not _KO.search(f):
            return f.strip()
    for f in ctx.p.features:
        if f.strip() and not _KO.search(f):
            return f.strip()
    return ""


MOVE_EN = dict(prompts.MOVE_EN)
SHOT_EN = dict(prompts.SHOT_EN)
ANGLE_EN = dict(prompts.ANGLE_EN)


def _scene_texts(ctx, style: str, mixed: dict | None) -> list[tuple[str, str, list[str]]]:
    """장면별 (voice_over, caption, 규칙 위반으로 바꾼 코드). 기존 UGC 문장 생성 + 사실 검증 재사용."""
    prob = ctx.p.problem.strip()
    state: dict = {}
    short = ctx.short
    from ..director import clean_sentence
    if style == "problem" and prob:
        h = (f"{clean_sentence(prob)}, 은근 불편하죠", make_caption(f"{clean_sentence(prob)} 불편"))
    elif style == "result_first":
        h = (f"{short}, 먼저 이 모습부터 보세요", make_caption(f"{short} 먼저 [[이 모습]]"))
    elif style == "curiosity":
        h = (f"{short}, 이 부분 보이세요?", make_caption(f"{short} 이 부분"))
    else:
        h = (f"이게 뭘까요? {short}예요", make_caption(f"이게 뭘까요?"))
    neutral_h = (f"{short}, 이 부분 보이세요?", make_caption(f"{short} 이 부분"))
    concept = {"hook": {"text": h[0], "caption": h[1]}}
    out = []
    v, c = h
    v, c, fx = _safe(ctx, "hook", v, c, neutral_h)
    out.append((v, c, fx))
    dv, dc = _lines(ctx, concept, "demonstration", state)
    dv, dc, fx = _safe(ctx, "demonstration", dv, dc, (f"{short}, 직접 쓰는 모습이에요", f"[[{short}]] 직접 보기"))
    out.append((dv, dc, fx))
    bv, bc = _lines(ctx, concept, "benefit", state)
    cv, cc = "자세한 정보는 링크에서 확인하세요", "정보는 [[링크]]에서"
    bv, bc, fx1 = _safe(ctx, "benefit", bv, bc, ("실제 모습은 이래요", "실제 [[모습]]은 이래요"))
    cv, cc, fx2 = _safe(ctx, "cta", cv, cc, ("자세한 정보는 링크에서 확인하세요", "정보는 [[링크]]에서"))
    out.append((f"{bv}. {cv}", cc, fx1 + fx2))
    return out


def _common_blocks(ctx, mixed, category: str) -> dict:
    person = _pat(mixed, "person")
    mode = person.get("mode") or "selfie"
    if mode == "none":
        mode = "hands_only"
    cam = _pat(mixed, "camera")
    moves = cam.get("movements") or []
    sizes = cam.get("shot_sizes") or []
    angles = cam.get("angles") or []
    edit = _pat(mixed, "editing")
    gestures = [g for g in (person.get("gestures") or []) if not _KO.search(g)]
    return {"mode": mode, "person": PERSON_FACE[mode], "moves": moves, "sizes": sizes, "angles": angles, "gestures": gestures,
            "fast": (edit.get("cut_speed") in ("fast", "very_fast")) or (edit.get("avg_cut") or 9) <= 2.0,
            "location": LOCATION.get(category, LOCATION["general"]), "light": LIGHT.get(category, "soft natural daylight")}


def _continuity(c: dict) -> str:
    return (f"Continuity for all 3 scenes: the same ordinary person ({c['person']}), same casual outfit and hairstyle, same location ({c['location']}), "
            f"same {c['light']}, same single product, same vertical phone framing.")


def _fp(text: str) -> str:
    return " ".join(text.split())


def build(ctx, mixed: dict | None = None, *, product_reference: str | None = None, feature_en: list[str] | None = None) -> dict:
    """3-Scene Flow Prompt Package. mixed = Reference Mixer 결과(없으면 레퍼런스 없이 상품 정보만으로)."""
    category = ctx.category
    c = _common_blocks(ctx, mixed, category)
    style, style_why = _hook_style(ctx, mixed)
    texts = _scene_texts(ctx, style, mixed)
    feat = _feature_en(ctx, feature_en)
    feat_phrase = f"the main stated feature ({feat})" if feat else "the product's main stated feature, as visible on the real product in the reference photo (do not invent functions)"
    cont = _continuity(c)
    fast = c["fast"]
    mv = c["moves"]
    shots = c["sizes"]
    angs = c["angles"]
    hand = c["gestures"][0] if c["gestures"] else ""
    gesture_clause = f" Hand gesture pattern: {hand}." if hand else ""

    hook_action = {
        "problem": "starts mid-annoyance: the person shows the everyday small frustration this product is meant for (acted out with hands and a mildly annoyed expression), then the product is pulled into frame in the last second",
        "result_first": "opens directly on the satisfying end-state moment with the product in use, then cuts the viewer's curiosity forward to how it happens",
        "curiosity": "opens with a tight crop on one distinctive part of the product so the viewer wonders what it is, then a quick pull-back reveals more of it",
        "unexpected": "opens with the product suddenly entering the frame from off-screen into the person's hand in an unexpected, playful way",
    }[style]
    s1_move = MOVE_EN.get(mv[0], "fast handheld punch-in") if mv else "fast handheld punch-in"
    s1_shot = SHOT_EN.get(shots[0], "close-up") if shots else "close-up"
    s1_angle = ANGLE_EN.get(angs[0], "eye-level angle") if angs else "eye-level angle"
    s2_move = MOVE_EN.get(mv[1 % len(mv)], "slow push-in") if mv else "slow push-in"
    s2_shot = "close-up" if not shots else SHOT_EN.get(shots[min(1, len(shots) - 1)], "close-up")
    s3_move = "slow smooth pull-back settling into a steady hero framing"
    pace = "fast-paced energy, one quick dynamic reframe within the shot" if fast else "lively pace with one quick dynamic reframe within the shot"

    specs = [
        {"scene_number": 1, "role": "scroll_stopper", "title": "Scroll Stopper / Strong Hook", "duration": DURATIONS[0], "stage": "hook",
         "purpose": "첫 1~3초 안에 시선을 멈춘다 (" + {"problem": "문제 상황", "result_first": "결과 선공개", "curiosity": "궁금증", "unexpected": "예상 밖 제품 등장"}[style] + ")",
         "visual": "Phone-shot UGC opening with an immediate visual change in the first second; product only partly visible or revealed at the very end.",
         "person_action": f"The person {hook_action}. Expression: curious, slightly surprised.",
         "product_action": "Product enters or is partly visible; it is held in the right hand and not yet fully demonstrated.",
         "camera_shot": s1_shot, "camera_angle": s1_angle, "camera_movement": s1_move,
         "lighting": f"{c['light']}, slightly imperfect real-life exposure", "environment": f"{c['location']}, lived-in, not a studio set",
         "start_state": "Black-to-live cut; person already mid-action, no intro.", "end_state": "Product held in the right hand, about 40% of it visible, person looking at it.",
         "sfx": "pop"},
        {"scene_number": 2, "role": "product_demo", "title": "Product Demo / Hero Use", "duration": DURATIONS[1], "stage": "demonstration",
         "purpose": "사람이 실제로 제품을 쓰며 핵심 USP 1개를 보여준다",
         "visual": "Continuous, clear demonstration of one feature, product large and readable in frame, optional brief hero angle.",
         "person_action": f"The same person holds the product in the right hand and uses the left hand to demonstrate {feat_phrase}, in a single continuous natural motion. Expression: focused, interested.{gesture_clause}",
         "product_action": f"Demonstrates {feat_phrase}; the product stays unchanged, nothing else is added to it.",
         "camera_shot": s2_shot, "camera_angle": "eye-level angle, slightly above the hands", "camera_movement": s2_move,
         "lighting": f"same {c['light']} as scene 1", "environment": f"the same location as scene 1 ({c['location']})",
         "start_state": "Matches the end of scene 1: product in the right hand, same framing, now fully in view.", "end_state": "Feature clearly shown, product centered and fully visible for a beat.",
         "sfx": "pop"},
        {"scene_number": 3, "role": "result_hero_cta", "title": "Result / Hero Shot / CTA Ending", "duration": DURATIONS[2], "stage": "cta",
         "purpose": "사용 후 결과 + 제품 히어로 샷 + 자연스러운 CTA 마무리",
         "visual": "Calm satisfying result moment, then a clean hero shot of the product held toward the camera as a natural ending frame.",
         "person_action": "The same person finishes using the product with a relaxed, satisfied expression, then holds it in the right hand toward the camera with a friendly final look and a small nod.",
         "product_action": "Product shown fully and steadily in the right hand as the hero shot; no extra items.",
         "camera_shot": "medium close-up, product occupying about half of the frame", "camera_angle": "eye-level angle", "camera_movement": s3_move,
         "lighting": f"same {c['light']} as scene 1", "environment": f"the same location as scene 1 ({c['location']})",
         "start_state": "Matches the end of scene 2: same position, product visible.", "end_state": "Steady hero frame held for the last second (end-card friendly), no text.",
         "sfx": "ding"},
    ]
    scenes = []
    for sp, (vo, cap, fixed) in zip(specs, texts):
        n = sp["scene_number"]
        main = (f"Scene {n} of 3 — {sp['title']}. Vertical 9:16 smartphone UGC footage, TikTok commercial energy but real-life look, {pace if n == 1 else ('stable and clear' if n == 2 else 'confident closing beat')}, "
                f"duration {sp['duration']:.0f} seconds, single continuous shot. "
                f"Who/where: {c['person']}, at {c['location']}. "
                f"Action: {sp['person_action']} "
                f"Product: {sp['product_action']} Product Lock — identical to the attached reference photo (shape, proportions, color, logo, printed text, button positions). "
                f"Camera: {sp['camera_shot']}, {sp['camera_angle']}, {sp['camera_movement']}. Framing keeps the product readable, about {'40' if n == 1 else '70' if n == 2 else '50'}% of the frame visible. "
                f"Lighting: {sp['lighting']}. Background: {sp['environment']}. {cont} "
                f"Starts: {sp['start_state']} Ends: {sp['end_state']}")
        main = _fp(main)
        avoid = "; ".join(NEGATIVE)
        scenes.append({**sp, "voice_over": vo, "caption": cap, "is_cta": n == 3,
                       "duration_label": f"{sp['duration']:.0f}s", "time": [round(sum(DURATIONS[:n - 1]), 1), round(sum(DURATIONS[:n]), 1)],
                       "camera_shot_en": sp["camera_shot"], "product_fidelity_rules": list(PRODUCT_LOCK),
                       "negative_constraints": list(NEGATIVE), "text_fixed": fixed,
                       "flow_prompt": f"{main} Avoid: {avoid}.",
                       "video_prompt": f"{main} Avoid: {avoid}."})
    usage = []
    asp = (mixed or {}).get("aspects") or {}
    link = lambda a, n, what: usage.append({"scene": n, "aspect": a, "from": asp[a]["from"], "uses": what}) if a in asp else None
    link("hook", 1, "Hook 방식")
    link("camera", 1, "카메라 구도/움직임")
    link("person", 2, "인물·손동작")
    link("demonstration", 2, "시연 방식/제품 공개 타이밍")
    link("camera", 2, "카메라 움직임")
    link("editing", 1, "컷 속도")
    link("cta", 3, "CTA 구조")
    link("demonstration", 3, "결과/히어로 샷")
    pkg = {"version": 1, "format": "shopshorts.flow3_prompt_package", "provider_agnostic": True, "target": "Google Flow (copy-paste per scene)",
           "mode": "3_SCENE_FLOW", "hook_style": style, "hook_style_reason": style_why, "keywords": KEYWORDS,
           "product_reference": {"image": product_reference, "name": ctx.p.name, "rule": "Attach the real product photo as the reference/ingredient image for every scene."},
           "continuity": cont, "product_lock": list(PRODUCT_LOCK), "scenes": scenes,
           "voice_script": [s["voice_over"] for s in scenes], "captions": [s["caption"] for s in scenes], "total_seconds": sum(DURATIONS),
           "reference_usage": usage, "reference_mode": bool(asp),
           "assemble_note": "Flow 에서 Scene 1~3 을 각각 생성한 뒤 CapCut 등에서 순서대로 이어 붙이고, Voice Over/Caption/BGM 은 별도로 얹으세요.",
           "format_spec": {"aspect": "9:16", "resolution": "1080x1920", "audio": "video prompts carry visuals only; voice/captions/sfx/bgm are produced separately"}}
    pkg["copy_text"] = {"scene_1": scenes[0]["flow_prompt"], "scene_2": scenes[1]["flow_prompt"], "scene_3": scenes[2]["flow_prompt"],
                        "all": "\n\n".join(f"[Scene {s['scene_number']}]\n{s['flow_prompt']}" for s in scenes)}
    pkg["problems"] = validate(pkg, ctx)
    return pkg


def validate(pkg: dict, ctx=None) -> list[str]:
    """프롬프트 품질/안전 점검: 문제 목록 (비어 있으면 통과)."""
    probs = []
    sc = pkg["scenes"]
    if [s["scene_number"] for s in sc] != [1, 2, 3]:
        probs.append("Scene 이 정확히 1~3 이 아니에요")
    for s in sc:
        fp = s["flow_prompt"]
        if _KO.search(fp):
            probs.append(f"Scene {s['scene_number']}: 영상 프롬프트에 한국어가 섞였어요")
        for f in ("voice_over", "caption"):
            t = re.sub(r"[\[\]]", "", s[f]).strip()
            if len(t) >= 4 and t in fp:
                probs.append(f"Scene {s['scene_number']}: 영상 프롬프트에 {f} 문구가 섞였어요")
        if "Product Lock" not in fp or "9:16" not in fp:
            probs.append(f"Scene {s['scene_number']}: Product Lock/9:16 누락")
        if ctx is not None:
            bad = [i for i in line_issues(s["voice_over"] + " " + strip_marks(s["caption"]), ctx) if i["severity"] == "block"]
            if bad:
                probs.append(f"Scene {s['scene_number']}: 문구 규칙 위반 {bad[0]['code']}")
    return probs


# ------------------------------------------------------------------ 진입점
FIELDS = ("name", "description", "features", "problem", "target", "price", "category_hint", "my_take", "review_quotes", "before_after")


def make_context(product: dict, fingerprint: list[str] | None = None):
    from ..product import ProductInput
    from ..strategy import make_ctx
    p = ProductInput.from_dict({k: v for k, v in product.items() if k in FIELDS})
    return make_ctx(p, "UGC_REVIEW", "PRO", None, None, has_clip=False, pattern={"fingerprint": fingerprint or [], "story": {}, "hook": {}}), p


def translate_features(router, features: list[str]) -> list[str]:
    """한국어 특징을 짧은 영어 구절로 번역 (실제 LLM 이 있을 때만, 사실 추가 금지). 실패하면 빈 목록 → 프롬프트는 일반 문구를 쓴다."""
    feats = [f.strip() for f in features if f and f.strip()][:3]
    if not feats or router is None or not any(_KO.search(f) for f in feats):
        return []
    try:
        if not router.has_real("llm"):
            return []
        r = router.run("llm", "text", system="Translate each product feature into a short, literal English phrase (max 8 words). Do not add, embellish or infer anything. Output one phrase per line, same order, no numbering.",
                       user="\n".join(feats), temperature=0.0)
        lines = [re.sub(r"^[-*\d.\s]+", "", x).strip() for x in str(getattr(r, "text", r) or "").splitlines() if x.strip()]
        return [x for x in lines if x and not _KO.search(x) and len(x) <= 80][:3]
    except Exception:
        return []


def generate(product: dict, *, mixed: dict | None = None, product_reference: str | None = None, router=None) -> dict:
    """상품 정보(+선택: 레퍼런스 믹서 결과) → 3-Scene Flow 패키지. 상품명이 없으면 ValueError."""
    if not (product.get("name") or "").strip():
        raise ValueError("상품명이 필요해요")
    ctx, p = make_context(product, (mixed or {}).get("fingerprint"))
    return build(ctx, mixed, product_reference=product_reference, feature_en=translate_features(router, list(p.features)))


def apply_to_scenes(scenes: list, pkg: dict) -> list[str]:
    """Storyboard 장면 중 'AI 제품사용(AI_PRODUCT_UGC)' 으로 계획된 장면에만 Scene 프롬프트를 넣는다. AI_PRESENTER 등 다른 종류에는 넣지 않는다."""
    role = {"HOOK": 0, "DEMO": 1, "FEATURE": 1, "BENEFIT": 2, "CTA": 2}
    done = []
    for sc in scenes:
        ai = getattr(sc, "ai", None)
        if not ai or ai.get("kind") != "AI_PRODUCT_UGC":
            continue
        i = role.get(sc.scene_type)
        if i is None:
            continue
        ai["prompt_override"] = pkg["scenes"][i]["flow_prompt"]
        ai["flow3_scene"] = i + 1
        done.append(sc.scene_id)
    return done
