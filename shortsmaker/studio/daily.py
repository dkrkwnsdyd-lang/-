"""일상 속 상품 쇼츠 (콘텐츠 유형 DAILY): 일상 장면에 상품이 자연스럽게 나오는 쇼츠. 기본 유형(PRODUCT)과 같은 앱/편집 엔진을 쓰고 대본 구성만 다르다.

구성: 일상 한 장면(hook) → 자연스러운 등장(reveal) → 쓰는 순간(demo) → 가까이(detail) → 여운(benefit) → 가벼운 안내(cta)
원칙
- 판매 전략 엔진(구매 이유/Angle/Hook 경쟁/전환 점검) 대신 일상 구성: 강하게 파는 말투(상투구/압박/희소성)를 쓰지 않는다.
- 일상 장면의 장소/시간대는 사용자가 적은 메모(daily_notes)와 입력한 타깃만 쓴다. 입력이 없으면 구체적인 상황을 지어내지 않고 중립 문구를 쓴다.
- 1인칭 경험담("써봤는데")은 사용자가 '직접 써본 느낌(my_take)'을 줬을 때만. 효과/성능/후기/가격/할인은 입력에 있을 때만(기존 line_issues 안전 검사를 그대로 통과해야 함).
- 일상 사진/영상은 사용자가 올린 것만 사용 (AI 영상 없음, 비용 0). 일상 장면 사진이 없으면 그대로 말하고 제품 사진으로 만든다.
"""
from __future__ import annotations

from .director import clean_sentence, feature_lines, product_short, strip_marks, tail_phrase
from .strategy.common import line_issues, make_caption

PATTERN = "DAILY_MOMENT"
MAX_NOTES = 4
NOTE_MAX_CHARS = 16


def notes_of(p) -> list[str]:
    """사용자 일상 메모 정리: 한 줄당 짧게, 최대 4개, 중복 제거."""
    out: list[str] = []
    for n in getattr(p, "daily_notes", []) or []:
        n = clean_sentence(" ".join(str(n).split()))[:NOTE_MAX_CHARS].strip()
        if n and n not in out:
            out.append(n)
    return out[:MAX_NOTES]


def _safe(ctx, tts: str, cap: str, fallback: tuple[str, str]) -> tuple[str, str, bool]:
    bad = [i for i in line_issues(tts + " " + strip_marks(cap), ctx) if i["severity"] == "block"]
    return (fallback[0], fallback[1], True) if bad else (tts, cap, False)


def director_data(p, ctx) -> dict:
    """기존 파이프라인(direct_scenes)이 그대로 읽는 대본 입력(director_data)."""
    short = product_short(p.name) if p.name else "이 제품"
    notes = notes_of(p)
    feats = feature_lines([f for f in p.features if f.strip()]) if p.features else []
    target = clean_sentence(p.target)[:NOTE_MAX_CHARS] if getattr(p, "target", "") else ""
    fixed: list[str] = []
    n0 = notes[0] if notes else (f"{target}의 하루" if target else "")
    # hook: 일상 한 장면 (메모가 없으면 구체적 상황을 지어내지 않는다)
    if n0:
        hook = (f"{n0}, 이런 하루의 한 장면", make_caption(f"{n0} [[한 장면]]"))
    else:
        hook = (f"{short}가 있는 하루의 한 장면", make_caption(f"{short} 있는 [[하루]]"))
    # reveal: 장면 속에 자연스럽게 놓인 상품
    n1 = notes[1] if len(notes) > 1 else ""
    reveal = (f"{n1}에 놓인 {short}", make_caption(f"{n1} [[{short}]]")) if n1 else (f"그 곁에 있는 {short}", make_caption(f"곁에 있는 [[{short}]]"))
    # demo / detail: 입력한 특징을 '보이는 그대로' 설명
    demo = feats[0] if feats else (f"{short}를 쓰는 모습이에요", make_caption(f"{short} [[쓰는 모습]]"))
    n2 = notes[2] if len(notes) > 2 else ""
    if len(feats) > 1:
        detail = feats[1]
    elif n2:
        detail = (f"{n2}에도 {short}", make_caption(f"{n2} [[{short}]]"))
    else:
        detail = (f"가까이서 본 {short}", make_caption(f"가까이서 본 [[{short}]]"))
    # benefit: 사용자의 직접 써본 느낌이 있을 때만 그 말을, 없으면 보이는 모습만
    take = clean_sentence(getattr(p, "my_take", "") or "")
    benefit = (take, make_caption(take)) if take else ("일상 속에 이렇게 놓여 있어요", make_caption("일상 속에 [[이렇게]]"))
    cta = ("자세한 정보는 링크에서 확인하세요", "정보는 [[링크]]에서")
    neutral = {"hook": (f"{short}가 있는 하루의 한 장면", make_caption(f"{short} 있는 [[하루]]")), "reveal": (f"그 곁에 있는 {short}", make_caption(f"곁에 있는 [[{short}]]")),
               "demo": (f"{short}를 쓰는 모습이에요", make_caption(f"{short} [[쓰는 모습]]")), "detail": (f"가까이서 본 {short}", make_caption(f"가까이서 본 [[{short}]]")),
               "benefit": ("일상 속에 이렇게 놓여 있어요", make_caption("일상 속에 [[이렇게]]")), "cta": cta}
    beats = []
    for name, (tts, cap), feat in (("hook", hook, None), ("reveal", reveal, None), ("demo", demo, feats and p.features[0] or None),
                                   ("detail", detail, (p.features[1] if len(p.features) > 1 else None)), ("benefit", benefit, None), ("cta", cta, None)):
        tts, cap, replaced = _safe(ctx, tts, cap, neutral[name])
        if replaced:
            fixed.append(name)
        beats.append({"beat": name, "story_role": name, "tts_line": tts, "caption": cap, "feature": feat})
    return {"angles": [], "best_angle": "design", "story_pattern": PATTERN,
            "hook_candidates": [{"type": "daily_moment", "text": beats[0]["tts_line"], "caption": beats[0]["caption"]}], "beats": beats,
            "tension": "", "payoff": "", "_director": "daily_moment_v1",
            "_grounding": {"final": "daily_moment", "notes_used": notes, "lines_replaced_for_safety": fixed}}


def summary(p, data: dict, identity, has_clip: bool) -> dict:
    """결과에 남길 일상 모드 요약 (무엇을 썼는지, 일상 소스가 부족한지)."""
    lifestyle = [ph["path"] for ph in identity.photos if ph.get("background") == "busy"]
    warnings = []
    if not lifestyle and not has_clip:
        warnings.append("일상 장면 사진/영상이 없어 제품 사진 위주로 만들었어요. 일상 속에서 찍은 사진이나 영상을 넣으면 훨씬 자연스러워요")
    if len(lifestyle) == 1 and not has_clip and len(identity.photos) > 1:
        warnings.append("일상 장면 사진이 1장뿐이라 같은 사진이 반복되지 않도록 다른 사진도 섞었어요. 일상 사진을 2~3장 더 넣으면 훨씬 자연스러워요")
    if not notes_of(p):
        warnings.append("일상 장면 메모가 없어 구체적인 상황 없이 만들었어요 (장소/시간대를 적으면 자막에 반영돼요)")
    return {"content_type": "DAILY", "pattern": PATTERN, "notes_used": notes_of(p), "lifestyle_photos": len(lifestyle), "has_video": has_clip,
            "lines_replaced_for_safety": data["_grounding"]["lines_replaced_for_safety"], "warnings": warnings}
