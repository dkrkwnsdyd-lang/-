"""Reference Mixer: 여러 레퍼런스에서 '연출 원리'만 골라 현재 상품에 맞게 재구성한다 (영상/대사/장면을 잇거나 복제하지 않는다).

영역별로 점수가 가장 높은 레퍼런스를 고르되, 상품과 맞지 않으면 쓰지 않고 이유를 남긴다 (스타일이 좋아도 상품에 안 맞으면 불채택):
- 문제/불편 단계(Problem/Agitation)와 문제 Hook 은 입력에 해결하는 불편(problem)이 있을 때만
- Before/After 는 사용자가 전/후 자료를 줬을 때만 (효과를 지어내지 않음)
- Demonstration 은 제품 특징이 입력에 있을 때만
- 결과 선공개(result_first)는 시연 자료가 없으면 쓰지 않음
"""
from __future__ import annotations

from . import schema

ASPECTS = ("hook", "person", "demonstration", "before_after", "camera", "editing", "cta", "structure")


def _s(ref: dict, key: str, default: float = 50.0) -> float:
    v = ref["analysis"]["scores"].get(key)
    return float(v) if v is not None else default


def _valid(refs: list[dict]) -> list[dict]:
    return [r for r in refs if r.get("analysis") and r.get("status") in ("VERIFIED", "PARTIAL")]


def _fit_hook(a: dict, ctx) -> tuple[bool, str]:
    h = a["hook"]
    if (h["pattern"] in ("problem_first",) or h["problem_raised"]) and not ctx.p.problem.strip():
        return False, "입력에 해결하는 불편이 없어 문제 제기형 Hook 은 쓰지 않아요"
    if h["result_first"] and not ctx.p.features:
        return False, "시연할 특징이 없어 결과 선공개 Hook 은 쓰지 않아요"
    return True, ""


def mix(refs: list[dict], ctx, picks: dict | None = None) -> dict:
    """refs: analyzer 결과 목록(실패 포함). 반환: {references, adopted, rejected, aspects, fingerprint, warnings}"""
    ok = _valid(refs)
    out = {"references": [{"id": r["id"], "status": r["status"], "source_ref": r["source_ref"], "error": r.get("error", ""),
                           "total": round(sum(v for v in (r["analysis"] or {}).get("scores", {}).values() if v is not None) / max(1, sum(1 for v in (r["analysis"] or {}).get("scores", {}).values() if v is not None)), 1) if r.get("analysis") else None}
                          for r in refs],
           "adopted": [], "rejected": [], "aspects": {}, "fingerprint": [], "warnings": []}
    failed = [r for r in refs if r not in ok]
    if failed:
        out["warnings"].append(f"레퍼런스 {len(failed)}개는 분석에 실패해 제외하고 나머지 {len(ok)}개로 진행했어요")
    if not ok:
        out["warnings"].append("분석에 성공한 레퍼런스가 없어요")
        return out
    fp: set[str] = set()
    for r in ok:
        fp |= set(r.get("fingerprint") or [])
    out["fingerprint"] = sorted(fp)
    by_id = {r["id"]: r for r in ok}
    P = ctx.p

    def adopt(aspect, ref, pattern, reason):
        out["adopted"].append({"aspect": aspect, "from": ref["id"], "source": ref["source_ref"], "pattern": pattern, "reason": reason})
        out["aspects"][aspect] = {"from": ref["id"], "pattern": pattern}

    def reject(aspect, reason, ref=None):
        out["rejected"].append({"aspect": aspect, "from": ref["id"] if ref else None, "reason": reason})

    def choose(aspect, scorer, fit=None):
        pick = by_id.get((picks or {}).get(aspect))
        cands = [pick] if pick else sorted(ok, key=lambda r: -scorer(r["analysis"], r))
        for r in cands:
            good, why = fit(r["analysis"]) if fit else (True, "")
            if good:
                return r, ("사용자가 선택" if pick else "")
            reject(aspect, why, r)
        return None, ""

    # hook
    r, note = choose("hook", lambda a, r: _s(r, "hook_strength") + 1.5 * len(a["hook"]["attention_devices"]), lambda a: _fit_hook(a, ctx))
    if r:
        a = r["analysis"]["hook"]
        adopt("hook", r, {k: a[k] for k in ("pattern", "attention_devices", "problem_raised", "curiosity", "twist", "result_first")},
              note or f"Hook 점수 {_s(r, 'hook_strength'):.0f} 최고 · 상품 정보와 맞음")
    # person staging
    r, note = choose("person", lambda a, r: _s(r, "ugc_authenticity") + 2 * len(a["ugc_person"]["authenticity_cues"]))
    if r:
        up = r["analysis"]["ugc_person"]
        adopt("person", r, {k: up[k] for k in ("mode", "face_visible", "gaze", "gestures", "product_grip", "authenticity_cues", "expression")}, note or f"UGC 진짜 같은 느낌 {_s(r, 'ugc_authenticity'):.0f} 최고")
    # demonstration
    if P.features:
        r, note = choose("demonstration", lambda a, r: _s(r, "demonstration_clarity") + (8 if a["product"]["usage_process"] else 0), lambda a: (bool(a["product"]["demonstration"] or a["product"]["usage_process"]), "시연/사용 과정이 없는 레퍼런스"))
        if r:
            pr = r["analysis"]["product"]
            adopt("demonstration", r, {k: pr[k] for k in ("closeup", "usage_process", "demonstration", "result_screen", "usp_emphasis", "first_appearance")}, note or f"시연 명확도 {_s(r, 'demonstration_clarity'):.0f} 최고")
    else:
        reject("demonstration", "입력에 제품 특징이 없어 시연 연출을 만들 수 없어요")
    # before/after: 사용자 데이터가 있을 때만
    ba = [r for r in ok if r["analysis"]["product"]["before_after"]]
    if ba and (P.before_after or []):
        adopt("before_after", ba[0], {"before_after": True}, "사용자가 전/후 자료를 줘서 채택")
    elif ba:
        reject("before_after", "사용자가 전/후 자료를 주지 않아 Before/After 는 쓰지 않아요 (효과를 지어내지 않음)", ba[0])
    # camera
    r, note = choose("camera", lambda a, r: _s(r, "ugc_authenticity") * 0.6 + _s(r, "editing_quality") * 0.4 + 2 * len(a["camera"]["shot_sizes"]), lambda a: (bool(a["camera"]["shot_sizes"] or a["camera"]["movements"]), "카메라 정보 없음"))
    if r:
        cm = r["analysis"]["camera"]
        adopt("camera", r, dict(cm), note or "카메라/구도 점수 최고")
    # editing
    r, note = choose("editing", lambda a, r: _s(r, "editing_quality"), lambda a: (bool(a["editing"]["avg_cut"] or a["editing"]["cut_speed"]), "편집 정보 없음"))
    if r:
        ed = r["analysis"]["editing"]
        adopt("editing", r, dict(ed), note or f"편집 점수 {_s(r, 'editing_quality'):.0f} 최고")
    # CTA
    r, note = choose("cta", lambda a, r: _s(r, "sales_connection") + (4 if any(s["stage"] == "cta" for s in a["structure"]) else 0), lambda a: (bool(a["cta"]["style"]), "CTA 정보 없음"))
    if r:
        adopt("cta", r, dict(r["analysis"]["cta"]), note or f"판매 연결 {_s(r, 'sales_connection'):.0f} 최고")
    # structure (광고 구조 순서): 상품 정보에 근거가 없는 단계는 뺀다
    def struct_fit(a):
        st = [s["stage"] for s in a["structure"]]
        return (len(st) >= 3, "광고 구조(단계)를 읽지 못한 레퍼런스")
    r, note = choose("structure", lambda a, r: sum(_s(r, k) for k in schema.SCORE_KEYS) / len(schema.SCORE_KEYS) + len({s["stage"] for s in a["structure"]}), struct_fit)
    if r:
        stages, dropped = [], []
        for s in r["analysis"]["structure"]:
            st = s["stage"]
            if st in ("problem", "agitation") and not P.problem.strip():
                dropped.append(st)
                continue
            if st == "proof" and not (getattr(P, "my_take", "") or P.review_quotes):
                dropped.append(st)               # 사용 경험/후기 근거가 없으면 Proof 단계(후기)는 만들지 않는다
                continue
            if not stages or stages[-1] != st:
                stages.append(st)
        if dropped:
            reject("structure", f"입력 근거가 없어 {', '.join(sorted(set(dropped)))} 단계는 뺐어요", r)
        adopt("structure", r, {"stages": stages, "emotional_tone": r["analysis"]["emotional_tone"]}, note or "광고 구조 완성도 최고")
    return out
