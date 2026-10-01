"""STEP 1 SELLING POINT ANALYSIS: 구매 이유 후보(>=5, 가능하면) 평가 -> PRIMARY_SELLING_POINT 하나."""
from __future__ import annotations

import re

from .common import Ctx, ask, clean_sentence, grade, jaccard, line_issues, num, scale_scores, tail_phrase, tokens, unsupported, verify, weighted

CRITERIA = ("instant_understanding", "problem_strength", "purchase_desire", "shortform_fit", "visual_potential", "target_relevance")
WEIGHTS = {"instant_understanding": 0.20, "problem_strength": 0.20, "purchase_desire": 0.20,
           "shortform_fit": 0.15, "visual_potential": 0.10, "target_relevance": 0.15}
KINDS = ("FUNCTIONAL", "EMOTIONAL", "PAIN_POINT", "DIFFERENTIATION")
VISUAL_WORDS = ("접", "뚜껑", "버튼", "LED", "손잡이", "슬림", "모양", "색", "크기", "작", "쏙", "케이스", "스포이드", "펼", "세우", "걸")

SYSTEM = (
    "너는 한국 쇼핑 쇼츠 전략가다. 상품의 '구매 이유' 후보를 분석한다. 기능 나열 금지. 4가지 관점으로 후보를 최소 5개 만든다: "
    "FUNCTIONAL(시간절약/편의/공간/휴대/관리 등), EMOTIONAL(사용 전후 감정 변화 - 귀찮음→편안함 등), "
    "PAIN_POINT(현재 불편→왜 불편한가→제품이 어떻게 해결하는가), DIFFERENTIATION(실제 확인 가능한 범위에서 기존 방식/일반 대안과의 차이; 확인 안 되면 만들지 않는다). "
    'JSON: {"product_analysis":{"shape","color","usage_context","target_customer","pain_point","desire"},'
    '"candidates":[{"text":"한 문장 구매 이유","kind":"FUNCTIONAL|EMOTIONAL|PAIN_POINT|DIFFERENTIATION","feature":"근거가 된 입력 특징(없으면 빈 문자열)",'
    '"pain":{"now":"","why":"","solution":""},"emotion":{"from":"","to":""},'
    '"scores":{"instant_understanding":0-100,"problem_strength":0-100,"purchase_desire":0-100,"shortform_fit":0-100,"visual_potential":0-100,"target_relevance":0-100}}]} '
    "근거가 입력에 없는 후보는 만들지 않는다. 모든 장점을 한 영상에 넣으려 하지 않는다."
)


def rule_candidates(ctx: Ctx) -> tuple[dict, list[dict]]:
    p = ctx.p
    short = ctx.short
    feats = [clean_sentence(f) for f in p.features if f.strip()]
    prob = clean_sentence(p.problem) if p.problem else ""
    analysis = {"shape": "", "color": ", ".join(map(str, ctx.colors[:2])) if ctx.colors else "", "usage_context": "",
                "target_customer": p.target or "", "pain_point": prob, "desire": ""}
    out = []
    for i, f in enumerate(feats):
        linked = bool(prob) and jaccard(f, prob) > 0.0
        vis = 80 if any(w in f for w in VISUAL_WORDS) else 50
        out.append({"text": f, "kind": "FUNCTIONAL", "feature": f, "pain": None, "emotion": None,
                    "scores": {"instant_understanding": max(40, 92 - 2 * max(0, len(f) - 10)),
                               "problem_strength": 80 if linked else (55 if prob else 40),
                               "purchase_desire": 58 + (6 if re.search(r"\d", f) else 0) - 2 * i,
                               "shortform_fit": 85 if len(f) <= 16 else 62, "visual_potential": vis,
                               "target_relevance": 70 if p.target and jaccard(f, p.target) > 0 else 55}})
    if prob:
        sol = feats[0] if feats else ""
        out.append({"text": f"불편: {prob}", "kind": "PAIN_POINT", "feature": sol,
                    "pain": {"now": prob, "why": "", "solution": sol}, "emotion": None,
                    "scores": {"instant_understanding": 82, "problem_strength": 90, "purchase_desire": 66, "shortform_fit": 80,
                               "visual_potential": 62, "target_relevance": 72 if p.target else 60}})
        out.append({"text": "불편함 → 덜 신경 쓰는 상태", "kind": "EMOTIONAL", "feature": sol,
                    "pain": None, "emotion": {"from": prob, "to": "그 불편을 덜 신경 쓰는 상태"},
                    "scores": {"instant_understanding": 70, "problem_strength": 72, "purchase_desire": 62, "shortform_fit": 72,
                               "visual_potential": 50, "target_relevance": 62}})
    return analysis, out


def _normalize(ctx: Ctx, raw: list[dict], basis: str) -> list[dict]:
    cands, seen = [], []
    for c in raw:
        text = clean_sentence(str(c.get("text", "")))
        if not text or any(jaccard(text, s) > 0.8 for s in seen):
            continue
        issues = [i for i in line_issues(text, ctx) if i["severity"] == "block"]
        if issues:                                             # 근거 없는 판매 주장은 후보에서 제외
            continue
        kind = c.get("kind") if c.get("kind") in KINDS else "FUNCTIONAL"
        feature = re.sub(r"^특징:\s*", "", str(c.get("feature") or "")).strip()
        if feature and feature not in ctx.p.features:        # 입력 특징 문장으로 정규화 (가장 비슷한 것, 없으면 비움)
            near = max(ctx.p.features, key=lambda f: jaccard(f, feature), default="")
            feature = near if near and jaccard(near, feature) > 0.2 else ""
        _s = scale_scores(c.get("scores"))
        sc = {k: num(_s.get(k), 50) for k in CRITERIA}
        rel = grade(text, ctx)
        has_evidence = bool(feature) or rel == "A" or (kind == "PAIN_POINT" and ctx.p.problem)
        if not has_evidence and kind != "EMOTIONAL":
            rel = "B"
        total = weighted(sc, WEIGHTS)
        if rel != "A":
            total = round(total - 6, 1)                    # 입력 근거가 약하면 감점 (AI 해석)
        seen.append(text)
        cands.append({"id": f"SP{len(cands) + 1}", "text": text, "kind": kind, "feature": feature,
                      "pain": c.get("pain") if kind == "PAIN_POINT" else None,
                      "emotion": c.get("emotion") if kind == "EMOTIONAL" else None,
                      "scores": sc, "total": total, "reliability": rel, "basis": basis})
    cands.sort(key=lambda c: -c["total"])
    for i, c in enumerate(cands):
        c["id"] = f"SP{i + 1}"
    return cands


def run(router, ctx: Ctx, picks: dict | None = None) -> dict:
    raw = ask(router, SYSTEM, ctx.brief())
    basis = "llm" if raw else "rule"
    analysis, rcands = ({}, [])
    if raw and isinstance(raw.get("candidates"), list):
        analysis = raw.get("product_analysis") if isinstance(raw.get("product_analysis"), dict) else {}
        cands = _normalize(ctx, raw["candidates"], "llm")
    else:
        cands = []
    if len(cands) < 2:                                       # LLM 결과가 비었거나 거의 걸러졌으면 규칙 기반
        analysis, rcands = rule_candidates(ctx)
        cands = _normalize(ctx, rcands, "rule")
        basis = "rule"
    pick = (picks or {}).get("selling_point")
    if basis == "llm":                                       # 구매 이유 문장도 입력 사실로 검증: 근거 없는 후보는 C(확인 불가)로 표시하고 대표로 쓰지 않는다
        problems = verify(router, ctx, [c["text"] for c in cands])
        for c in cands:
            pr = unsupported(problems, c["text"]) if problems is not None else None
            if problems is None:
                c["reliability"] = "B"
                c["note"] = "사실 검증 불가 (AI 해석)"
            elif pr:
                c["reliability"], c["note"] = "C", f"입력에 없는 내용 포함: {pr.get('phrase')}"
                c["total"] = round(c["total"] - 15, 1)
        cands.sort(key=lambda c: -c["total"])
        for i, c in enumerate(cands):
            c["id"] = f"SP{i + 1}"
    primary = next((c for c in cands if c["id"] == pick), None) or next((c for c in cands if c["reliability"] != "C"), None)
    return {"basis": basis, "product_analysis": analysis, "candidates": cands, "primary": primary,
            "shortage": len(cands) < 5,
            "reason": (f"6개 기준 가중 평균 {primary['total']}점 (순간 이해/문제 강도/구매 욕구 각 20%)" if primary else "후보 없음")}
