"""STEP 4 SALES SCRIPT ENGINE: HOOK -> PROBLEM -> SOLUTION -> PROOF -> CTA (영상 스타일별 구조).

- Hook 은 STEP 3 에서 고른 BEST_HOOK 을 그대로 쓴다 (스크립트 단계에서 다시 쓰지 않음).
- PROOF 는 확인된 자료(사용자 후기 문구 / 직접 써본 느낌 / 입력된 기능 / 실제 시연)로만 만든다. 없으면 가짜 후기를 만들지 않고 '실제 모습/기능' 표현으로 대체한다.
- CTA 문구는 STEP 6 에서 확정한다 (여기서는 자리표시).
"""
from __future__ import annotations

import re

from ..director import BEAT_DURATION, BEAT_PURPOSE, feature_lines, josa_end
from .common import (FILLER, PRAISE, Ctx, STYLE_KO, ask, clean_sentence, grade, jaccard, line_issues, make_caption, speak_seconds, strip_marks, tail_phrase,
                     unsupported, verify)

ROLE = {"hook": "HOOK", "problem": "PROBLEM", "reveal": "SOLUTION", "demo": "SOLUTION", "detail": "SOLUTION", "benefit": "PROOF", "cta": "CTA"}
VISIBILITY = {"hook": "HINT", "problem": "NONE", "reveal": "FULL", "demo": "PARTIAL", "detail": "PARTIAL", "benefit": "FULL", "cta": "FULL"}
STRUCTURE = {
    "FAST_COMMERCE": ["hook", "reveal", "demo", "detail", "benefit", "cta"],
    "STORY_AD": ["hook", "problem", "reveal", "demo", "detail", "benefit", "cta"],
    "UGC_REVIEW": ["hook", "problem", "reveal", "demo", "detail", "benefit", "cta"],
}
STYLE_GUIDE = {
    "FAST_COMMERCE": "빠른 컷, 강한 Hook, 실제 상품 중심. 문제 장면은 생략 가능. 설명 최소, 12~18초.",
    "STORY_AD": "상황→문제→감정→전환→상품 Reveal→해결. 이야기의 결말처럼 이어지는 짧은 광고. 15~25초.",
    "UGC_REVIEW": "자연스러운 구어체 소개형. 1인칭 사용 경험/후기 표현은 '직접 써본 느낌(사용자 작성)'이나 실제 후기 문구가 입력에 있을 때만. 없으면 말투만 편하게 하고 경험을 지어내지 않는다(실제로는 UGC_PRESENTATION/UGC_DEMO). 15~20초.",
}

SYSTEM = (
    "너는 한국 쇼핑 쇼츠 판매 대본 작가다. 구조: HOOK→PROBLEM→SOLUTION→PROOF→CTA. 영상 스타일에 맞게 beats 를 쓴다. "
    "beat 이름: hook, problem, reveal, demo, detail, benefit(=PROOF), cta. 한 beat 의 대사는 말로 3.5초(약 24자) 이내, 자막은 한 줄 13자 이내 최대 2줄, 강조는 [[ ]]. "
    "PROOF 는 allowed_facts 의 실제 기능/후기/직접 써본 느낌만 근거로 쓰고, 근거가 없으면 '실제 모습/기능 설명'으로 쓴다(가짜 후기 금지). "
    "problem 은 allowed_facts 에 '해결하는 불편'이 있을 때만 쓴다. 한 영상에서 모든 장점을 말하지 않는다 - primary_selling_point 하나에 집중. "
    "기능 나열, 의미 없는 형용사, 과한 칭찬 금지. cta 는 자리표시로 짧게 써도 된다(별도 단계에서 확정). "
    "reference_pattern 이 있으면 beat_plan 의 순서/역할(story_role: situation/pain/pain_emotion/turning/reveal/demo/result/proof)을 그대로 따라 beats 를 쓰되, 참고 영상의 문장/내용은 모르는 상태에서 "
    "현재 상품의 allowed_facts 로만 새 문장을 쓴다. 외국어 직역체, 중국식 광고 표현, 과도한 감탄(!!), '놓치지 마세요/필수템/신세계' 같은 표현 금지. "
    'JSON: {"beats":[{"beat","story_role","tts_line","caption","feature":"이 장면이 보여주는 입력 특징 문장(없으면 빈 문자열)","visual_prompt":"실제 사진/영상으로 무엇을 보여줄지 한 줄"}]}'
)


def structure_for(ctx: Ctx) -> list[str]:
    """영상 스타일별 beat 구조. FAST/12~15초 에서는 장면 수 한계(5)에 맞춰 곁가지(detail, problem)부터 줄인다 - Proof/CTA 는 남긴다."""
    st = list(STRUCTURE[ctx.style])
    if ctx.mode == "FAST" or getattr(ctx.p, "compact", False):
        st = [b for b in st if b != "detail"]
        if len(st) > 5:
            st = [b for b in st if b != "problem"]
    return st


def plan_for(ctx: Ctx) -> list[tuple[str, str]]:
    """(beat, story_role). Reference 패턴이 있으면 그 스토리 단계(상황/문제/감정/전환 …)를, 없으면 스타일 기본 구조."""
    pat = getattr(ctx, "pattern", None)
    if pat and (pat.get("story") or {}).get("beat_plan"):
        plan = [(x["beat"], x["role"]) for x in pat["story"]["beat_plan"]]
        if ctx.mode == "FAST" or getattr(ctx.p, "compact", False):          # 짧은 구조에서는 장면 수 한계(5)에 맞춰 감정/상황부터 줄인다
            for victim in (("problem", "pain_emotion"), ("problem", "situation"), ("benefit", "proof"), ("problem", "pain")):
                if len(plan) > 5 and victim in plan:
                    plan.remove(victim)
        return plan
    return [(b, b) for b in structure_for(ctx)]


def _proof_line(ctx: Ctx) -> tuple[str, str, str]:
    """(tts, caption, source) - 확인된 자료만."""
    p = ctx.p
    if p.review_quotes:
        q = clean_sentence(p.review_quotes[0])
        return f"사용해 본 분은 이렇게 말해요, {q}", make_caption(f"후기: {q}"), "review_quote(사용자 입력)"
    if getattr(p, "my_take", ""):
        t = clean_sentence(p.my_take)
        return t, make_caption(t), "my_take(사용자 작성)"
    return "실제 모습은 이래요", "실제 [[모습]]은 이래요", "real_product_view"


def rule_beats(ctx: Ctx, primary: dict | None, hook: dict | None) -> list[dict]:
    p, short = ctx.p, ctx.short
    prob = clean_sentence(p.problem) if p.problem else ""
    lines = feature_lines(p.features) or [(f"{short}, 한 번 보세요", f"[[{short}]]")]
    pf = (primary or {}).get("feature") or ""
    if pf and p.features:      # 핵심 구매 이유가 된 특징을 demo 로
        idx = next((i for i, f in enumerate(p.features) if clean_sentence(f) == clean_sentence(pf)), 0)
        lines = [lines[idx]] + [l for i, l in enumerate(lines) if i != idx] if idx < len(lines) else lines
        feats = [p.features[idx]] + [f for i, f in enumerate(p.features) if i != idx]
    else:
        feats = list(p.features)
    ugc = ctx.style == "UGC_REVIEW"
    out = []
    for beat, role in plan_for(ctx):
        if beat == "hook":
            out.append({"beat": "hook", "tts_line": (hook or {}).get("text") or f"{short}, 이 부분 보이세요?",
                        "caption": (hook or {}).get("caption") or make_caption(f"{short} 이 부분"), "feature": ""})
        elif beat == "problem" and role in ("situation", "pain", "pain_emotion"):
            if not prob:
                continue
            tail = tail_phrase(prob)
            hook_said = bool(hook and jaccard(hook.get("text", ""), prob) > 0.4)
            if role == "situation":
                tts = f"{p.target}이라면 한 번쯤 겪는 일이에요" if p.target else f"{prob}… 이런 상황이 있죠"
                cap = make_caption(f"{p.target} 한 번쯤" if p.target else f"{tail} 이런 상황", p.target or tail)
            elif role == "pain" and not hook_said:
                tts, cap = f"{prob}, 은근 불편하죠", make_caption(f"{tail} 불편", tail)
            else:                                                       # pain_emotion / Hook 이 이미 문제를 말한 경우: 감정 한 줄
                tts, cap = "그럴 때마다 괜히 신경 쓰이죠", make_caption("그럴 때마다 신경 쓰임", "신경")
            out.append({"beat": "problem", "tts_line": tts, "caption": cap, "feature": "", "story_role": role})
        elif beat == "problem":
            if not prob:
                continue
            tail = tail_phrase(prob)
            if hook and jaccard(hook.get("text", ""), prob) > 0.4:       # Hook 이 이미 문제를 말했으면 같은 말을 반복하지 않는다
                if ctx.style != "STORY_AD":
                    continue
                tts, cap = "그럴 때마다 괜히 신경 쓰이죠", make_caption("그럴 때마다 신경 쓰임", "신경")
            else:
                tts = f"{prob}… 은근 신경 쓰이죠" if ctx.style == "STORY_AD" else f"{prob}, 이런 거 있죠"
                cap = make_caption(f"{tail} 신경 쓰임", tail)
            out.append({"beat": "problem", "tts_line": tts, "caption": cap, "feature": ""})
        elif beat == "reveal" and role == "turning":
            out.append({"beat": "reveal", "tts_line": "그런데 이런 제품이 있어요", "caption": f"그런데 [[{short}]]", "feature": "", "story_role": role})
        elif beat == "reveal":
            shown = bool(prob) and (any(b["beat"] == "problem" for b in out) or jaccard(out[0]["tts_line"], prob) > 0.4)
            if shown:
                out.append({"beat": "reveal", "tts_line": "그럴 땐 이 제품이에요" if not ugc else (f"그래서 제가 본 게 이 {short}예요" if getattr(p, "my_take", "") or p.review_quotes else f"그래서 눈에 띈 게 이 {short}예요"),
                            "caption": f"그럴 땐 [[{short}]]", "feature": ""})
            else:
                out.append({"beat": "reveal", "tts_line": f"바로 이 {short}예요" if not ugc else (f"제가 본 건 이 {short}예요" if getattr(p, "my_take", "") or p.review_quotes else f"눈에 띈 건 이 {short}예요"), "caption": f"바로 이 [[{short}]]", "feature": ""})
        elif beat == "demo" and lines:
            out.append({"beat": "demo", "tts_line": lines[0][0], "caption": lines[0][1], "feature": feats[0] if feats else ""})
        elif beat == "detail":
            if len(lines) < 2 or ctx.style == "FAST_COMMERCE" and len(lines) < 3 and False:
                continue
            out.append({"beat": "detail", "tts_line": lines[1][0], "caption": lines[1][1], "feature": feats[1] if len(feats) > 1 else ""})
        elif beat == "benefit":
            tts, cap, src = _proof_line(ctx)
            out.append({"beat": "benefit", "tts_line": tts, "caption": cap, "feature": "", "proof_source": src, "story_role": role})
        elif beat == "cta":
            out.append({"beat": "cta", "tts_line": "자세한 정보는 링크에서 확인하세요", "caption": "정보는 [[링크]]에서", "feature": ""})
    return out


def _visual_for(b: dict, ctx: Ctx) -> tuple[str, str]:
    beat = b["beat"]
    src = "user_video" if (ctx.has_clip and beat in ("demo", "detail")) else "user_photo"
    prompt = b.get("visual_prompt") or {
        "hook": "제품이 보이는 실제 사진 (크게/가까이)", "problem": "불편한 상황이 드러나는 실제 사진 또는 제품 일부",
        "reveal": "제품 전체가 보이는 실제 사진", "demo": f"{b.get('feature') or '핵심 기능'}이 보이는 가까운 실제 사진/영상",
        "detail": f"{b.get('feature') or '디테일'} 클로즈업", "benefit": "실제 제품 모습", "cta": "제품 정면 마무리"}[beat]
    return src, prompt


def _finish(ctx: Ctx, beats: list[dict]) -> list[dict]:
    out, t = [], 0.0
    for i, b in enumerate(beats):
        lo, hi = BEAT_DURATION[b["beat"]]
        dur = round(min(hi, max(lo, speak_seconds(b["tts_line"]) + 0.35)), 2)
        src, prompt = _visual_for(b, ctx)
        out.append({"scene_id": f"S{i + 1}", "beat": b["beat"], "scene_role": ROLE[b["beat"]], "purpose": BEAT_PURPOSE[b["beat"]],
                    "time": [round(t, 2), round(t + dur, 2)], "duration": dur, "narration": strip_marks(b["tts_line"]),
                    "tts_line": b["tts_line"], "caption": b["caption"], "feature": b.get("feature") or "",
                    "visual_source": src, "visual_prompt": prompt, "product_visibility": VISIBILITY[b["beat"]],
                    "proof_source": b.get("proof_source", ""), "story_role": b.get("story_role") or b["beat"],
                    "reliability": grade(b["tts_line"] + " " + b["caption"], ctx)})
        t += dur
    return out


def _validate_llm(router, ctx: Ctx, raw: list[dict], primary: dict | None, hook: dict | None) -> list[dict] | None:
    """LLM beats 를 검증/보정. 근거 없는 줄은 규칙 기반 줄로 교체한다."""
    problems = verify(router, ctx, [" ".join(str(b.get("tts_line", "")).split()) for b in raw if b.get("beat") != "hook"])
    if problems is None:
        return None            # 사실 검증을 못 했으면 LLM 글은 쓰지 않는다
    plan = plan_for(ctx)
    allowed = {b for b, _ in plan}
    rb = rule_beats(ctx, primary, hook)
    fallback = {b["beat"]: b for b in rb}
    fb_role = {(b["beat"], b.get("story_role") or b["beat"]): b for b in rb}
    beats, seen = [], set()
    for b in raw:
        name = b.get("beat")
        brole = b.get("story_role") or name
        if name not in allowed or (name, brole) in seen and name != "detail":
            continue
        if name == "problem" and not ctx.p.problem.strip():
            continue
        tts = " ".join(str(b.get("tts_line", "")).split())
        cap = str(b.get("caption") or make_caption(tts))
        issues = [i for i in line_issues(tts + " " + strip_marks(cap), ctx) if i["severity"] == "block"]
        too_long = speak_seconds(tts) > 4.0
        unsup = unsupported(problems, tts)
        if unsup:
            issues = issues + [{"code": "unsupported", "detail": str(unsup.get("phrase"))}]
        if issues or too_long or not tts:
            fb = fb_role.get((name, brole)) or fallback.get(name)
            if not fb:
                continue
            tts, cap = fb["tts_line"], fb["caption"]
            b = {**b, "_replaced": [i["code"] for i in issues] + (["too_long"] if too_long else [])}
        if not (issues or too_long or not tts) and name in ("problem", "reveal", "demo", "detail", "benefit"):
            # 판매 주장이 실리는 장면은 문장 대부분이 입력 사실이어야 한다(등급 A). 풀어쓴 효과/인과('덕분에', '맞게 자극')는 규칙 문장으로 교체
            if grade(tts + " " + strip_marks(cap), ctx) != "A" and name in fallback:
                issues = issues + [{"code": "not_grounded", "detail": "입력 사실과 겹치지 않는 풀어쓴 표현"}]
                fb = fallback[name]
                tts, cap = fb["tts_line"], fb["caption"]
                b = {**b, "_replaced": ["not_grounded"]}
        tts = re.sub(r"\s{2,}", " ", PRAISE.sub("", FILLER.sub("", tts))).strip()
        feat = str(b.get("feature") or "")
        if feat and feat not in ctx.p.features:
            feat = max(ctx.p.features, key=lambda f: jaccard(f, feat), default="") if any(jaccard(f, feat) > 0.3 for f in ctx.p.features) else ""
        seen.add((name, brole))
        beats.append({"beat": name, "story_role": brole, "tts_line": tts, "caption": cap, "feature": feat, "visual_prompt": str(b.get("visual_prompt") or ""),
                      "proof_source": fallback.get("benefit", {}).get("proof_source", "") if name == "benefit" else "",
                      "replaced": b.get("_replaced", [])})
    if not beats:
        return None
    if hook:                                                   # BEST_HOOK 고정
        beats = [x for x in beats if x["beat"] != "hook"]
        beats.insert(0, {"beat": "hook", "tts_line": hook["text"], "caption": hook["caption"], "feature": ""})
    if beats[-1]["beat"] != "cta":
        beats = [x for x in beats if x["beat"] != "cta"] + [fallback.get("cta") or {"beat": "cta", "tts_line": "자세한 정보는 링크에서 확인하세요", "caption": "정보는 [[링크]]에서", "feature": ""}]
    order = ["hook", "problem", "reveal", "demo", "detail", "benefit", "cta"]
    beats.sort(key=lambda x: order.index(x["beat"]))           # 흐름 단절 방지 (공개 전 데모 등)
    if not any(b["beat"] == "reveal" for b in beats):
        return None
    return beats


def run(router, ctx: Ctx, primary: dict | None, angle: dict | None, hook: dict | None, picks: dict | None = None) -> dict:
    payload = {**ctx.brief(), "primary_selling_point": primary, "selected_angle": angle, "best_hook": hook,
               "style_guide": STYLE_GUIDE[ctx.style], "structure": structure_for(ctx)}
    pat = getattr(ctx, "pattern", None)
    if pat:                                                      # Reference 패턴: 구조 힌트만 (참고 영상의 문장/내용은 없음)
        payload["reference_pattern"] = {"beat_plan": (pat.get("story") or {}).get("beat_plan"), "emotion_curve": (pat.get("story") or {}).get("emotion_curve"),
                                        "story_roles_abstract": (pat.get("story") or {}).get("roles"), "rules": pat.get("rules")}
    raw = ask(router, SYSTEM, payload, temperature=0.6)
    beats, basis = None, "rule"
    if raw and isinstance(raw.get("beats"), list):
        beats = _validate_llm(router, ctx, raw["beats"], primary, hook)
        basis = "llm" if beats else "rule"
    if not beats:
        beats = rule_beats(ctx, primary, hook)
    scenes = _finish(ctx, beats)
    total = round(sum(s["duration"] for s in scenes), 2)
    evidence = bool(getattr(ctx.p, "my_take", "") or ctx.p.review_quotes)
    ugc_kind = ("UGC_REVIEW_VERIFIED" if evidence else ("UGC_DEMO" if ctx.has_clip else "UGC_PRESENTATION")) if ctx.style == "UGC_REVIEW" else ""
    return {"basis": basis, "style": ctx.style, "ugc_kind": ugc_kind, "style_ko": STYLE_KO[ctx.style], "structure": structure_for(ctx),
            "target_seconds": list(ctx.seconds), "estimated_seconds": total, "scenes": scenes,
            "replaced_lines": [{"scene_id": s["scene_id"], "why": b.get("replaced")} for s, b in zip(scenes, beats) if b.get("replaced")]}
