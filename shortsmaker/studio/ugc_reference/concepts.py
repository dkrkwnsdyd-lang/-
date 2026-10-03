"""UGC Concept Generator: Reference Mixer 결과 + Product Intelligence(구매 이유/Angle/Hook) → 서로 다른 UGC 광고 콘셉트 3개.

기존 전략 엔진 모듈을 그대로 재사용한다 (selling.run: 구매 이유·USP, angles.run: 판매 각도, hooks.run: 사실 검증을 거친 Hook).
콘셉트 B(사용 체험형)는 '가짜 후기' 방지 규칙을 따른다: 입력에 직접 써본 느낌(my_take)/실제 후기가 없으면 1인칭 사용 경험을 말하지 않고
UGC_PRESENTATION/UGC_DEMO 로 표시한다 (후기 근거가 있을 때만 UGC_REVIEW_VERIFIED).
"""
from __future__ import annotations

from ..strategy import angles as angles_mod
from ..strategy import hooks as hooks_mod
from ..strategy import selling as selling_mod
from ..strategy.common import STYLE_KO, Ctx

CONCEPT_TYPES = {
    "A": {"type": "problem_solution", "title": "문제 해결형", "stages": ["hook", "problem", "solution", "demonstration", "benefit", "cta"], "hook_type": "PROBLEM",
          "emotion": "불편함 → 해소", "uses": ("hook", "structure", "camera", "demonstration")},
    "B": {"type": "usage_experience", "title": "사용 체험형", "stages": ["hook", "solution", "demonstration", "benefit", "cta"], "hook_type": "EMPATHY",
          "emotion": "자연스러운 반응", "uses": ("person", "camera", "editing")},
    "C": {"type": "discovery", "title": "발견형", "stages": ["hook", "solution", "demonstration", "benefit", "cta"], "hook_type": "CURIOSITY",
          "emotion": "호기심 → 발견", "uses": ("hook", "demonstration", "cta")},
}


def _hook_for(hooks: dict, want: str) -> dict | None:
    cands = hooks.get("candidates") or []
    same = [h for h in cands if h["type"] == want]
    return (same or cands or [None])[0]


def generate(router, ctx: Ctx, mixed: dict) -> dict:
    """반환: {concepts:[A,B,C], selling, warnings}. LLM 이 없으면 규칙 기반으로 내려간다 (basis 로 표시)."""
    ctx.style = "UGC_REVIEW"
    sp = selling_mod.run(router, ctx)
    primary = sp.get("primary")
    an = angles_mod.run(router, ctx, primary)
    angle_pool = [a for a in an["angles"]] or []
    hooks = hooks_mod.run(router, ctx, primary, an.get("selected"), sp.get("product_analysis"))
    adopted = {a["aspect"]: a for a in mixed.get("adopted", [])}
    structure = (adopted.get("structure", {}).get("pattern") or {}).get("stages") or []
    evidence = bool(getattr(ctx.p, "my_take", "") or ctx.p.review_quotes)
    has_problem = bool(ctx.p.problem.strip())
    warnings = []
    concepts = []
    for i, (cid, spec) in enumerate(CONCEPT_TYPES.items()):
        stages = list(spec["stages"])
        notes = []
        if cid == "A" and not has_problem:
            stages = [s for s in stages if s != "problem"]
            notes.append("입력에 해결하는 불편이 없어 문제 단계를 뺀 시연 중심으로 구성했어요")
        if cid == "A" and has_problem and "agitation" in structure:
            stages.insert(stages.index("problem") + 1, "agitation")
        if cid == "B" and evidence:
            stages.insert(stages.index("benefit") + 1, "proof")
        hook = _hook_for(hooks, spec["hook_type"])
        angle = angle_pool[i % len(angle_pool)] if angle_pool else None
        uses = [a for a in spec["uses"] if a in adopted]
        ref_patterns = [{"aspect": a, "from": adopted[a]["from"], "reason": adopted[a]["reason"]} for a in uses]
        ugc_kind = ("UGC_REVIEW_VERIFIED" if evidence else ("UGC_DEMO" if ctx.has_clip else "UGC_PRESENTATION")) if cid == "B" else ""
        reasons = [f"{spec['title']}: " + ("입력에 해결하는 불편이 있어 문제→해결 구조가 어울려요" if cid == "A" and has_problem else
                                          "사람이 직접 쓰는 모습으로 자연스러운 느낌을 줘요" if cid == "B" else "궁금증을 만들고 제품 특징을 보여주는 구조예요")]
        if ref_patterns:
            reasons.append("레퍼런스 패턴: " + ", ".join(f"{p['aspect']}" for p in ref_patterns))
        if cid == "B" and not evidence:
            notes.append("직접 써본 느낌/실제 후기 입력이 없어 '써봤다'는 표현 없이 체험 장면만 보여줘요 (UGC_PRESENTATION)")
        concepts.append({"id": cid, "type": spec["type"], "title": spec["title"], "stages": stages,
                         "hook": {"text": hook["text"], "caption": hook["caption"], "type": hook["type"]} if hook else {"text": "", "caption": "", "type": spec["hook_type"]},
                         "target": ctx.p.target or "(입력 없음)", "selling_angle": {"title": angle["title"], "premise": angle["premise"], "axis": angle["axis"]} if angle else None,
                         "emotion": spec["emotion"], "main_usp": (primary or {}).get("feature") or (primary or {}).get("text") or "",
                         "reference_patterns": ref_patterns, "reason": " / ".join(reasons), "ugc_kind": ugc_kind, "notes": notes,
                         "uses_person_mode": (adopted.get("person", {}).get("pattern") or {}).get("mode")})
    rec = "A" if has_problem else "C"
    for c in concepts:
        c["recommended"] = c["id"] == rec
    if not primary:
        warnings.append("구매 이유(USP)를 정하지 못했어요 - 상품 특징을 입력하면 더 좋아져요")
    return {"concepts": concepts, "selling": {"primary": primary, "basis": sp.get("basis")}, "angles_basis": an.get("basis"), "hooks_basis": hooks.get("basis"),
            "recommended": rec, "warnings": warnings}
