"""STEP 2 DIFFERENTIATION ANGLE: 같은 카테고리 영상의 흔한 패턴과 다른 판매 각도를 찾는다.

주의: 카테고리 '흔한 패턴'은 외부 영상을 실제로 수집·분석한 값이 아니라 일반적 경향(B, 실측 아님)이다.
각도는 2개를 고르되 Hook 문장만 다른 것이 아니라 Problem/Scene/Emotion/Reveal/CTA 방향 전체가 달라야 한다.
"""
from __future__ import annotations

from .common import Ctx, ask, clean_sentence, grade, jaccard, line_issues, num, scale_scores, tail_phrase, weighted

AXES = ("USAGE_TIMING", "TARGET", "EMOTION", "PAIN_POINT", "UNEXPECTED_CONTEXT", "COMPARISON")
CRITERIA = ("originality", "product_fit", "empathy", "hook_potential", "story_potential", "visual_potential", "purchase_connection")
WEIGHTS = {"originality": 0.18, "product_fit": 0.22, "empathy": 0.14, "hook_potential": 0.14,
           "story_potential": 0.10, "visual_potential": 0.10, "purchase_connection": 0.12}

COMMON = {  # 카테고리별 일반적 경향 (B: 실측 아님)
    "kitchen": {"hook_pattern": "불편 질문형 / 비포-애프터", "product_reveal": "초반 3초 이내 클로즈업", "selling_point": "편의·세척",
                "story_structure": "문제→제품→기능 나열", "caption_style": "큰 글씨 키워드", "usage_scene": "주방 조리대",
                "comparison_style": "기존 제품 대비", "cta_style": "프로필 링크", "emotion_pattern": "편리함"},
    "living": {"hook_pattern": "정리 전/후", "product_reveal": "정리된 공간과 함께", "selling_point": "공간 절약",
               "story_structure": "어질러진 방→정리", "caption_style": "큰 글씨", "usage_scene": "거실/방",
               "comparison_style": "정리 전후", "cta_style": "링크 안내", "emotion_pattern": "후련함"},
    "electronics": {"hook_pattern": "스펙 나열 / 성능 질문", "product_reveal": "언박싱", "selling_point": "성능·휴대",
                    "story_structure": "스펙→기능", "caption_style": "스펙 수치", "usage_scene": "책상/이동 중",
                    "comparison_style": "타사 비교", "cta_style": "구매 링크", "emotion_pattern": "만족"},
    "camping": {"hook_pattern": "풍경 + 장비 공개", "product_reveal": "사용 장면 중 등장", "selling_point": "휴대·설치",
                "story_structure": "캠핑 장면→장비 소개", "caption_style": "감성 자막", "usage_scene": "야외",
                "comparison_style": "기존 장비", "cta_style": "링크", "emotion_pattern": "여유"},
    "fitness": {"hook_pattern": "통증/피로 공감", "product_reveal": "사용 장면", "selling_point": "강도·휴대",
                "story_structure": "문제→사용 시연", "caption_style": "큰 글씨", "usage_scene": "운동 후",
                "comparison_style": "마사지샵 대비", "cta_style": "링크", "emotion_pattern": "개운함"},
    "beauty": {"hook_pattern": "피부 고민 공감", "product_reveal": "텍스처 클로즈업", "selling_point": "사용감",
               "story_structure": "고민→제품→루틴", "caption_style": "부드러운 자막", "usage_scene": "아침/밤 루틴",
               "comparison_style": "기존 제품", "cta_style": "링크", "emotion_pattern": "자신감"},
    "general": {"hook_pattern": "문제 제기 질문", "product_reveal": "초반 공개", "selling_point": "기능 나열",
                "story_structure": "문제→제품→기능", "caption_style": "키워드 강조", "usage_scene": "일반",
                "comparison_style": "기존 방식", "cta_style": "프로필 링크", "emotion_pattern": "편리함"},
}

SYSTEM = (
    "너는 한국 쇼핑 쇼츠 차별화 전략가다. 입력의 PRIMARY_SELLING_POINT 를 가진 상품을 같은 카테고리의 흔한 쇼핑 영상(common_patterns)과 "
    "다른 각도로 파는 방법을 찾는다. 축: USAGE_TIMING(언제 쓰는가), TARGET(누구에게 필요한가), EMOTION(감정 변화), PAIN_POINT(구체적 문제), "
    "UNEXPECTED_CONTEXT(흔한 광고가 안 다루는 사용 상황), COMPARISON(경쟁 제품이 아니라 기존 방식/수동 방식/제품 없이 해결하던 방식과 비교). "
    "각도를 최소 5개(서로 다른 축) 만든다. 사용 시점/대상/상황은 allowed_facts 에서 도출 가능한 것만 쓴다 - 입력에 없는 상황을 지어내지 않는다. "
    "각도 하나는 Hook 문장만이 아니라 problem/scene/emotion/reveal/cta 방향이 모두 달라야 한다. "
    'JSON: {"angles":[{"axis","title","premise","story_form":"짧은 구조 설명","direction":{"hook","problem","scene","emotion","reveal","cta"},'
    '"evidence":["근거가 된 allowed_facts 문장"],"scores":{"originality","product_fit","empathy","hook_potential","story_potential","visual_potential","purchase_connection"}}]}'
)


def rule_angles(ctx: Ctx, primary: dict | None) -> list[dict]:
    p, short = ctx.p, ctx.short
    prob = clean_sentence(p.problem) if p.problem else ""
    feat = (primary or {}).get("feature") or (clean_sentence(p.features[0]) if p.features else "")
    out = []
    if prob:
        out.append({"axis": "PAIN_POINT", "title": "그 불편 그대로 보여주기", "premise": f"'{prob}' 상황을 먼저 보여주고 해결책으로 공개",
                    "story_form": "문제 상황 → 공개 → 해결 시연",
                    "direction": {"hook": f"문제 제기: {prob}", "problem": "불편한 순간을 짧게", "scene": "불편 → 해결 시연",
                                  "emotion": "답답함 → 후련함", "reveal": "문제 직후", "cta": "불편을 계속 겪기 전에"},
                    "evidence": [f"해결하는 불편(사용자 입력): {prob}"],
                    "scores": {"originality": 55, "product_fit": 88, "empathy": 86, "hook_potential": 80, "story_potential": 70,
                               "visual_potential": 66, "purchase_connection": 80}})
        out.append({"axis": "COMPARISON", "title": "그냥 참던 방식과 비교", "premise": "제품 없이 해결하던 방식과 나란히 보여주기",
                    "story_form": "기존 방식 → 제품 방식 비교", "direction": {"hook": "기존 방식의 번거로움 지적", "problem": "기존 방식 시연",
                                                                          "scene": "나란히 비교(실제 시연 필요)", "emotion": "'이게 되네' 하는 놀람",
                                                                          "reveal": "비교 직전", "cta": "차이를 직접 확인"},
                    "evidence": [f"해결하는 불편(사용자 입력): {prob}"],
                    "scores": {"originality": 62, "product_fit": 70, "empathy": 66, "hook_potential": 68, "story_potential": 72,
                               "visual_potential": 74, "purchase_connection": 70}})
    if p.target:
        out.append({"axis": "TARGET", "title": f"{p.target}에게 말 걸기", "premise": f"대상({p.target})이 바로 알아보게 시작",
                    "story_form": "대상 호출 → 공개 → 기능", "direction": {"hook": f"{p.target}을(를) 직접 호출", "problem": "대상의 상황",
                                                                         "scene": "대상이 쓰는 모습", "emotion": "'내 얘기네' 공감", "reveal": "대상 호출 직후",
                                                                         "cta": "나에게 맞는지 확인"},
                    "evidence": [f"대상: {p.target}"],
                    "scores": {"originality": 60, "product_fit": 74, "empathy": 78, "hook_potential": 70, "story_potential": 60,
                               "visual_potential": 58, "purchase_connection": 66}})
    if feat:
        out.append({"axis": "UNEXPECTED_CONTEXT", "title": "기능 하나만 끝까지 시연", "premise": f"'{feat}' 한 가지를 가까이서 보여주기",
                    "story_form": "기능 클로즈업 → 전체 공개", "direction": {"hook": "기능 장면부터 시작", "problem": "생략 가능",
                                                                         "scene": "기능 클로즈업", "emotion": "'오 이런 게 있네' 호기심",
                                                                         "reveal": "기능 확인 후 전체 공개", "cta": "나머지는 링크에서"},
                    "evidence": [f"특징: {feat}"],
                    "scores": {"originality": 66, "product_fit": 82, "empathy": 58, "hook_potential": 66, "story_potential": 56,
                               "visual_potential": 82, "purchase_connection": 70}})
    if prob:
        out.append({"axis": "EMOTION", "title": "귀찮음에서 편안함으로", "premise": "감정 변화 중심으로 짧게",
                    "story_form": "감정(귀찮음) → 전환 → 안도", "direction": {"hook": "공감 한 줄", "problem": "짜증나는 순간",
                                                                         "scene": "전환 순간", "emotion": "귀찮음 → 편안함", "reveal": "전환점",
                                                                         "cta": "그 감정에서 벗어나기"},
                    "evidence": [f"해결하는 불편(사용자 입력): {prob}"],
                    "scores": {"originality": 58, "product_fit": 70, "empathy": 82, "hook_potential": 66, "story_potential": 78,
                               "visual_potential": 56, "purchase_connection": 66}})
    return out


def _normalize(ctx: Ctx, raw: list[dict], basis: str) -> list[dict]:
    out = []
    for a in raw:
        axis = a.get("axis") if a.get("axis") in AXES else None
        title, premise = clean_sentence(str(a.get("title", ""))), clean_sentence(str(a.get("premise", "")))
        if not title or not premise:
            continue
        d = a.get("direction") if isinstance(a.get("direction"), dict) else {}
        bad = [i for i in line_issues(f"{title} {premise}", ctx) if i["severity"] == "block"]
        if bad:
            continue
        _s = scale_scores(a.get("scores"))
        sc = {k: num(_s.get(k), 50) for k in CRITERIA}
        ev = [str(e) for e in (a.get("evidence") or []) if e][:3]
        out.append({"axis": axis or "UNEXPECTED_CONTEXT", "title": title, "premise": premise, "story_form": str(a.get("story_form", "")),
                    "direction": {k: str(d.get(k, "")) for k in ("hook", "problem", "scene", "emotion", "reveal", "cta")},
                    "evidence": ev, "scores": sc, "total": weighted(sc, WEIGHTS) - (0 if ev else 8),
                    "reliability": "A" if ev else "B", "basis": basis})
    out.sort(key=lambda a: -a["total"])
    for i, a in enumerate(out):
        a["id"] = f"AN{i + 1}"
    return out


def select_two(angles: list[dict], pick: str | None = None) -> tuple[dict | None, dict | None]:
    """서로 다른 방향 2개: 같은 축/비슷한 premise 는 제외. 구조(story_form/direction)가 달라야 한다."""
    if not angles:
        return None, None
    first = next((a for a in angles if a["id"] == pick), angles[0])
    second = None
    for a in angles:
        if a["id"] == first["id"] or a["axis"] == first["axis"]:
            continue
        if jaccard(a["premise"], first["premise"]) > 0.5 or jaccard(a["story_form"], first["story_form"]) > 0.6:
            continue
        second = a
        break
    return first, second


def run(router, ctx: Ctx, primary: dict | None, picks: dict | None = None) -> dict:
    common = COMMON.get(ctx.category, COMMON["general"])
    payload = {**ctx.brief(), "primary_selling_point": primary, "common_patterns": common}
    raw = ask(router, SYSTEM, payload, temperature=0.7)
    angles, basis = [], "rule"
    if raw and isinstance(raw.get("angles"), list):
        angles = _normalize(ctx, raw["angles"], "llm")
        basis = "llm"
    if len(angles) < 2:
        angles, basis = _normalize(ctx, rule_angles(ctx, primary), "rule"), "rule"
    first, second = select_two(angles, (picks or {}).get("angle"))
    return {"basis": basis, "category": ctx.category,
            "common_patterns": {"patterns": common, "reliability": "B", "note": "일반적 경향(외부 영상 실측 아님)"},
            "angles": angles, "selected": first, "alternative": second, "shortage": len(angles) < 5}
