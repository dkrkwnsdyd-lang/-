"""UGC Storyboard Generator: 선택한 콘셉트 + 믹서 결과 + 상품 정보 → 3~5초 단위 Scene 목록.

장면 필드: scene_number, time, stage, visual, person_action, product_action, camera_shot, camera_movement, voice_over, caption, sfx, purpose.
대사/자막은 현재 상품 입력(특징/불편/대상)만 사용하고, 사실 검증(line_issues: 근거 없는 주장/상투구/가짜 사용 경험/복제)을 통과해야 한다. 걸리면 중립 문장으로 교체.
카메라/인물 연출은 믹서가 채택한 레퍼런스 패턴(샷 크기, 움직임, 제스처, 인물 모드)을 따른다.
"""
from __future__ import annotations

from ..director import clean_sentence, feature_lines, josa_end, tail_phrase
from ..strategy.common import Ctx, line_issues, make_caption, strip_marks

DURATION = {"hook": 3.0, "problem": 4.0, "agitation": 3.0, "solution": 4.0, "demonstration": 5.0, "proof": 4.0, "benefit": 4.0, "cta": 3.0}
PURPOSE = {"hook": "Hook: 첫 3초에 시선을 잡는다", "problem": "Problem: 타깃의 불편을 보여준다", "agitation": "Agitation: 불편을 한 번 더 체감시킨다",
           "solution": "Solution: 제품을 해결책으로 등장시킨다", "demonstration": "Demonstration: 핵심 특징을 직접 보여준다", "proof": "Proof: 입력된 근거로 신뢰를 만든다",
           "benefit": "Benefit: 입력된 특징 기준의 장점을 정리한다", "cta": "CTA: 행동으로 연결한다"}
SHOT_DEFAULT = {"hook": "close_up", "problem": "medium", "agitation": "close_up", "solution": "medium", "demonstration": "close_up", "proof": "medium", "benefit": "medium", "cta": "medium"}
SHOT_KO = {"extreme_close_up": "익스트림 클로즈업", "close_up": "클로즈업", "medium": "미디엄 샷", "wide": "와이드 샷"}
MOVE_KO = {"handheld": "스마트폰 핸드헬드", "zoom": "천천히 줌", "push_in": "푸시 인", "pan": "팬", "tilt": "틸트", "static": "고정"}
ANGLE_KO = {"eye_level": "눈높이", "high": "하이앵글", "low": "로우앵글", "top_down": "탑다운", "pov": "POV(1인칭)"}


def _pattern(mixed: dict, aspect: str) -> dict:
    return (mixed.get("aspects", {}).get(aspect) or {}).get("pattern") or {}


def _person_phrase(mode: str | None, gestures: list[str], grip: str) -> tuple[str, str]:
    """(사람 행동 설명, 제품 잡는 방식)"""
    g = gestures[0] if gestures else ""
    grip = grip or "한 손으로 자연스럽게 든다"
    if mode == "hands_only":
        return f"얼굴 없이 손만 등장해 제품을 다룬다{(' · ' + g) if g else ''}", grip
    if mode == "pov":
        return f"1인칭 시점으로 제품을 쓰는 사람의 손과 팔이 보인다{(' · ' + g) if g else ''}", grip
    if mode == "talking_head":
        return f"사람이 카메라를 보며 편하게 이야기하듯 제품을 보여준다{(' · ' + g) if g else ''}", grip
    return f"스마트폰으로 직접 찍듯 사람이 제품을 들고 보여준다{(' · ' + g) if g else ''}", grip


def _lines(ctx: Ctx, concept: dict, stage: str, state: dict) -> tuple[str, str]:
    """단계별 (voice_over, caption). 입력된 사실만 사용."""
    p, short = ctx.p, ctx.short
    prob = clean_sentence(p.problem) if p.problem else ""
    feats = feature_lines([f for f in p.features if f.strip()]) if p.features else []
    k = state.setdefault("feat_i", 0)
    if stage == "hook":
        h = concept["hook"]
        return h["text"] or f"{short}, 이 부분 보이세요?", h["caption"] or make_caption(f"{short} 이 부분")
    if stage == "problem":
        return f"{prob}, 은근 불편하죠", make_caption(f"{tail_phrase(prob)} 불편", tail_phrase(prob))
    if stage == "agitation":
        return "그럴 때마다 괜히 신경 쓰이죠", make_caption("그럴 때마다 신경 쓰임", "신경")
    if stage == "solution":
        return (f"그럴 땐 이 {short}예요", f"그럴 땐 [[{short}]]") if prob else (f"바로 이 {short}예요", f"바로 이 [[{short}]]")
    if stage == "demonstration":
        if feats:
            i = min(k, len(feats) - 1)
            state["feat_i"] = k + 1
            return feats[i]
        return f"{short}, 직접 쓰는 모습이에요", f"[[{short}]] 직접 보기"
    if stage == "benefit":
        if len(feats) > 1:
            i = min(state.get("feat_i", 1), len(feats) - 1)
            return feats[i]
        return "실제 모습은 이래요", "실제 [[모습]]은 이래요"
    if stage == "proof":
        if p.review_quotes:
            q = clean_sentence(p.review_quotes[0])
            return f"사용해 본 분은 이렇게 말해요, {q}", make_caption(f"후기: {q}")
        if getattr(p, "my_take", ""):
            t = clean_sentence(p.my_take)
            return t, make_caption(t)
        return "실제 모습은 이래요", "실제 [[모습]]은 이래요"
    return "자세한 정보는 링크에서 확인하세요", "정보는 [[링크]]에서"


def _safe(ctx: Ctx, stage: str, vo: str, cap: str, fallback: tuple[str, str]) -> tuple[str, str, list[str]]:
    bad = [i for i in line_issues(vo + " " + strip_marks(cap), ctx) if i["severity"] == "block"]
    if bad:
        return fallback[0], fallback[1], [b["code"] for b in bad]
    return vo, cap, []


def build(ctx: Ctx, concept: dict, mixed: dict) -> dict:
    """반환: {concept_id, scenes[], total_seconds, warnings}"""
    person = _pattern(mixed, "person")
    cam = _pattern(mixed, "camera")
    edit = _pattern(mixed, "editing")
    mode = person.get("mode") or "selfie"
    sizes = cam.get("shot_sizes") or []
    moves = cam.get("movements") or ["handheld"]
    angles = cam.get("angles") or ["eye_level"]
    sfx_style = edit.get("sfx") or "sparse"
    scenes, t, state, warnings = [], 0.0, {}, []
    neutral = {"hook": (f"{ctx.short}, 이 부분 보이세요?", make_caption(f"{ctx.short} 이 부분")), "cta": ("자세한 정보는 링크에서 확인하세요", "정보는 [[링크]]에서")}
    for i, stage in enumerate(concept["stages"]):
        dur = DURATION[stage]
        vo, cap = _lines(ctx, concept, stage, state)
        fb = neutral.get(stage, ("이 제품 정보를 보여드릴게요", "[[제품]] 정보"))
        vo, cap, fixed = _safe(ctx, stage, vo, cap, fb)
        if fixed:
            warnings.append(f"Scene {i + 1}: 문구가 규칙(근거 없는 주장/가짜 경험/복제 등: {', '.join(fixed)})에 걸려 중립 문장으로 바꿨어요")
        size = sizes[i % len(sizes)] if sizes else SHOT_DEFAULT[stage]
        if stage in ("hook", "demonstration") and "close_up" in sizes:
            size = "close_up"
        move = moves[i % len(moves)]
        angle = angles[i % len(angles)]
        person_action, grip = _person_phrase(mode, person.get("gestures") or [], person.get("product_grip") or "")
        prod = {"hook": "제품 일부가 화면에 먼저 보이거나 불편한 상황이 보인다", "problem": "제품은 아직 보이지 않거나 일부만 보인다", "agitation": "불편한 상황이 한 번 더 보인다",
                "solution": f"제품 전체가 처음 또렷하게 등장한다 ({grip})", "demonstration": f"입력된 특징을 직접 조작해 보여준다 ({grip})", "proof": "제품과 입력된 근거를 함께 보여준다",
                "benefit": "제품을 사용하는 모습을 정리해서 보여준다", "cta": "제품을 정면으로 보여주며 마무리한다"}[stage]
        if stage in ("problem", "agitation") and mode == "hands_only":
            person_action = "얼굴 없이 손만 보이며 불편한 동작을 한다"
        visual = f"{PURPOSE[stage].split(':')[0]} — " + {"hook": "스마트폰으로 찍은 듯한 첫 화면에서 시선을 끈다", "problem": "타깃이 불편을 겪는 상황을 직접 보여준다", "agitation": "같은 불편이 반복되는 모습",
                                                       "solution": "제품이 해결책으로 등장", "demonstration": "특징을 직접 쓰는 모습", "proof": "입력된 근거 확인", "benefit": "사용 후 장면 정리", "cta": "제품 정면 마무리"}[stage]
        scenes.append({"scene_number": i + 1, "time": [round(t, 1), round(t + dur, 1)], "duration": dur, "stage": stage, "visual": visual, "person_action": person_action,
                       "product_action": prod, "camera_shot": size, "camera_shot_ko": SHOT_KO[size], "camera_angle": angle, "camera_angle_ko": ANGLE_KO[angle],
                       "camera_movement": move, "camera_movement_ko": MOVE_KO[move], "voice_over": vo, "caption": cap,
                       "sfx": ("pop" if stage in ("hook", "demonstration") and sfx_style != "none" else "whoosh" if stage == "solution" and sfx_style == "frequent" else
                               "ding" if stage == "cta" and sfx_style != "none" else ""),
                       "purpose": PURPOSE[stage]})
        t += dur
    return {"concept_id": concept["id"], "concept_type": concept["type"], "scenes": scenes, "total_seconds": round(t, 1), "person_mode": mode, "warnings": warnings,
            "bgm": edit.get("bgm_mood") or "calm", "ugc_kind": concept.get("ugc_kind", "")}
