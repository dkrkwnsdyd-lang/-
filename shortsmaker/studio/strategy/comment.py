"""STEP 5 COMMENT TRIGGER ENGINE: 댓글을 '요구'하지 않고, 대답하고 싶어지는 지점을 만든다.

방식 3종(OPINION_SPLIT / EXPERIENCE_SHARE / CURIOSITY)에서 상품과 영상에 가장 맞는 하나, 문장 후보 5개 -> 가장 자연스러운 하나.
판매 흐름이 깨지면(짧은 영상/FAST/장면 수 한계) 삽입하지 않는다. 호기심형은 영상에서 아직 안 쓴 실제 특징이 있을 때만 쓴다(없는 정보로 낚지 않음).
"""
from __future__ import annotations

import re

from ..director import clean_sentence, tail_phrase
from .common import Ctx, ask, grade, jaccard, line_issues, make_caption, num, scale_scores, speak_seconds, strip_marks, tokens, unsupported, verify

METHODS = ("OPINION_SPLIT", "EXPERIENCE_SHARE", "CURIOSITY")
PLACEMENTS = ("after_problem", "after_solution", "after_proof", "before_cta", "after_cta")
MAX_SECONDS = 3.0

SYSTEM = (
    "너는 쇼핑 쇼츠 댓글 유도 장치 설계자다. 댓글을 직접 요구하지 않는다('댓글 남겨주세요','여러분 생각은?' 금지). "
    "방식: OPINION_SPLIT(실제 구매자가 고민할 선택지, 예: 기능 vs 디자인 - 선택지는 allowed_facts 의 실제 특징이어야 함), "
    "EXPERIENCE_SHARE(자기 경험을 말하고 싶게 만든다 - 입력된 불편에서만 출발), CURIOSITY(영상에서 아직 말하지 않은 실제 특징이 있을 때만). "
    "문장 후보 5개(서로 다른 문장, 말로 2.5초 = 약 17자 이내)를 만들고 각각 0~100 점수를 매긴다. 라벨처럼 나열하지 말고 자연스러운 구어체 질문으로 쓴다(예: 'A vs B, 뭐가 더 끌려요?'). "
    'JSON: {"lines":[{"method","text","scores":{"naturalness","relevance","flow_fit"}}]}'
)


def _key(f: str) -> str:
    f = clean_sentence(f)
    words = f.split()
    return " ".join(words[:2]) if len(f) > 10 else f


def used_features(script: dict) -> set[str]:
    return {s["feature"] for s in script["scenes"] if s.get("feature")}


def rule_lines(ctx: Ctx, script: dict) -> list[dict]:
    p = ctx.p
    prob = clean_sentence(p.problem) if p.problem else ""
    feats = [clean_sentence(f) for f in p.features if f.strip()]
    out = []
    pairs = [(feats[i], feats[j]) for i in range(len(feats)) for j in range(i + 1, len(feats))][:3]
    for n, (fa, fb) in enumerate(pairs):
        a, b = _key(fa), _key(fb)
        out.append({"method": "OPINION_SPLIT", "text": f"{a} vs {b}, 뭐가 더 끌려요?" if n % 2 == 0 else f"{a} 아니면 {b}, 하나만 고른다면?"})
    if prob:
        lead = prob if len(prob.replace(" ", "")) <= 9 else tail_phrase(prob)
        out += [{"method": "EXPERIENCE_SHARE", "text": f"{lead}, 이런 적 있죠?"},
                {"method": "EXPERIENCE_SHARE", "text": f"{lead} 때 나만의 방법이 있다면?"}]
    unused = [f for f in feats if f not in used_features(script)]
    if unused:
        out.append({"method": "CURIOSITY", "text": f"{unused[0]}, 알고 계셨어요?"})
    return out


def _valid(ctx: Ctx, script: dict, line: dict) -> tuple[bool, str]:
    t, m = strip_marks(line["text"]), line["method"]
    if line_issues(t, ctx):
        return False, "안전 규칙 위반(직접 요구/근거 없는 주장 등)"
    if speak_seconds(t) > MAX_SECONDS:
        return False, f"말하기에 {speak_seconds(t)}초 - 판매 흐름을 끊음"
    feats = [clean_sentence(f) for f in ctx.p.features]
    if m == "OPINION_SPLIT":
        hit = sum(1 for f in feats if tokens(t) & tokens(f))
        if hit < 2:
            return False, "선택지가 입력된 실제 특징 2개가 아님"
    elif m == "EXPERIENCE_SHARE":
        if not ctx.p.problem or not (tokens(t) & tokens(ctx.p.problem)):
            return False, "입력된 불편과 연결되지 않음"
    elif m == "CURIOSITY":
        unused = [f for f in feats if f not in used_features(script)]
        if not any(tokens(t) & tokens(f) for f in unused):
            return False, "영상에서 아직 안 쓴 실제 특징이 없음 (없는 정보로 궁금하게 만들 수 없음)"
    else:
        return False, "알 수 없는 방식"
    return True, ""


def _skip_reason(ctx: Ctx, script: dict) -> str:
    n = len(script["scenes"])
    if ctx.mode == "FAST" or getattr(ctx.p, "compact", False):
        return "짧은 구조(FAST/12~15초)에서는 판매 흐름을 우선해 삽입하지 않음"
    if n >= 8:
        return "장면 수 한계(8)에 도달해 삽입하지 않음"
    if script["estimated_seconds"] < 14:
        return "영상이 14초 미만이라 판매 흐름을 우선해 삽입하지 않음"
    return ""


def run(router, ctx: Ctx, script: dict, picks: dict | None = None) -> dict:
    payload = {**ctx.brief(), "script": [{"beat": s["beat"], "narration": s["narration"], "feature": s["feature"]} for s in script["scenes"]],
               "unused_features": [f for f in ctx.p.features if f not in used_features(script)]}
    raw = ask(router, SYSTEM, payload, temperature=0.8)
    lines, basis = [], "rule"
    if raw and isinstance(raw.get("lines"), list):
        lines = [{"method": l.get("method"), "text": " ".join(str(l.get("text", "")).split()), "scores": l.get("scores") or {}}
                 for l in raw["lines"] if isinstance(l, dict) and l.get("text")]
        basis = "llm"
        problems = verify(router, ctx, [l["text"] for l in lines])
        if problems is None:
            lines, basis = [], "rule"
        else:
            bad = [l for l in lines if unsupported(problems, l["text"])]
            lines = [l for l in lines if l not in bad]
    ok, rejected = [], []
    for source in (lines, rule_lines(ctx, script)):
        for l in source:
            good, why = _valid(ctx, script, l)
            (ok if good else rejected).append({**l, "why": why} if not good else l)
        if len(ok) >= 3:
            break
        basis = "rule" if source is not lines and not ok else basis
    for l in ok:
        sc = scale_scores(l.get("scores"))
        nat = num(sc.get("naturalness"), 62) - (8 if speak_seconds(l["text"]) > 2.4 else 0)
        rel = num(sc.get("relevance"), 60 + 20 * min(1, len(tokens(l["text"]) & tokens(f"{ctx.p.problem} {' '.join(ctx.p.features)}"))))
        flow = num(sc.get("flow_fit"), 65)
        l["total"] = round(0.45 * nat + 0.30 * rel + 0.25 * flow, 1)
        l["caption"] = make_caption(l["text"])
    ok.sort(key=lambda l: -l["total"])
    seen, uniq = [], []
    for l in ok:
        if all(jaccard(l["text"], s) < 0.6 for s in seen):
            uniq.append(l)
            seen.append(l["text"])
    for i, l in enumerate(uniq):
        l["id"] = f"CT{i + 1}"
    chosen = next((l for l in uniq if l["id"] == (picks or {}).get("comment")), None) or (uniq[0] if uniq else None)
    skip = _skip_reason(ctx, script) if chosen else "근거 있는 댓글 유도 문장을 만들 수 없음 (억지로 만들지 않음)"
    place = "before_cta" if ctx.style != "STORY_AD" else "after_proof"
    return {"basis": basis, "candidates": uniq[:5], "rejected": rejected[:8], "method": chosen["method"] if chosen else None,
            "selected": chosen, "placement": place, "placement_options": list(PLACEMENTS), "insert": bool(chosen and not skip),
            "skip_reason": skip}


def apply(script: dict, comment: dict) -> dict:
    """삽입이 승인되면 별도 짧은 장면(beat=benefit, kind=comment_trigger)으로 넣는다 (대사와 자막이 같이 나오도록)."""
    if not comment.get("insert") or not comment.get("selected"):
        return script
    sel, place = comment["selected"], comment["placement"]
    scenes = [dict(s) for s in script["scenes"]]
    idx = {"after_problem": next((i for i, s in enumerate(scenes) if s["beat"] == "problem"), None),
           "after_solution": max((i for i, s in enumerate(scenes) if s["scene_role"] == "SOLUTION"), default=None),
           "after_proof": next((i for i, s in enumerate(scenes) if s["scene_role"] == "PROOF"), None),
           "before_cta": len(scenes) - 2, "after_cta": len(scenes) - 1}.get(place)
    if idx is None:
        idx = len(scenes) - 2
    new = {"scene_id": "", "beat": "benefit", "scene_role": "PROOF", "purpose": "대답하고 싶어지는 지점", "time": [0, 0],
           "duration": 1.8, "narration": strip_marks(sel["text"]), "tts_line": sel["text"], "caption": sel["caption"], "feature": "",
           "visual_source": "user_photo", "visual_prompt": "제품 실제 모습 유지", "product_visibility": "FULL", "proof_source": "",
           "kind": "comment_trigger", "reliability": "B"}
    scenes.insert(idx + 1, new)
    return renumber({**script, "scenes": scenes})


def renumber(script: dict) -> dict:
    from .script import BEAT_DURATION
    t = 0.0
    for i, s in enumerate(script["scenes"]):
        lo, hi = BEAT_DURATION[s["beat"]]
        s["duration"] = round(min(hi, max(lo, speak_seconds(s["tts_line"]) + 0.35)), 2)
        s["scene_id"] = f"S{i + 1}"
        s["time"] = [round(t, 2), round(t + s["duration"], 2)]
        t += s["duration"]
    script["estimated_seconds"] = round(t, 2)
    return script
