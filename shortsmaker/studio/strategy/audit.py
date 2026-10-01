"""STEP 7 CONVERSION AUDIT: 렌더 전에 대본/구성을 스스로 점검한다.

점수는 '측정 가능한 것은 코드로 계산'하고(basis=rule), LLM 판정이 있으면 주관 항목만 절반 반영(basis=llm+rule)한다.
LLM 이 후하게 점수를 줘도 코드가 계산한 상한(근거 없는 Proof, 긴 Hook 등)은 넘지 못한다.
Funnel: SCROLL_STOP -> ATTENTION -> INTEREST -> PROBLEM_RECOGNITION -> PRODUCT_DESIRE -> TRUST -> ACTION
"""
from __future__ import annotations

import re

from .common import (scale_scores, CLICHE, DIRECT_COMMENT, FILLER, PRAISE, Ctx, ask, clean_sentence, grade, jaccard, line_issues, num, speak_seconds,
                     strip_marks, tokens)

METRICS = ("hook_strength", "selling_point_clarity", "purchase_motivation", "trust_proof", "cta_strength", "retention",
           "information_density", "visual_selling_power")
FUNNEL = ("SCROLL_STOP", "ATTENTION", "INTEREST", "PROBLEM_RECOGNITION", "PRODUCT_DESIRE", "TRUST", "ACTION")
RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
GATE_MIN = {"hook_strength": 60, "selling_point_clarity": 60, "cta_strength": 55, "information_density": 50, "retention": 50}
THOUGHT = {"hook_long": "그래서 이게 뭔데?", "late_reveal": "언제 제품 보여주는데?", "repeat": "이미 이해했는데 왜 계속 말하지?",
           "ad": "광고네.", "unrelated": "나랑 관계없는데?", "enumeration": "기능만 계속 나열하네", "long_line": "말이 너무 빨라서 못 따라가겠다"}

SYSTEM = (
    "너는 쇼핑 쇼츠 전환 감사관이다. 입력 script 를 보고 Funnel(SCROLL_STOP→ATTENTION→INTEREST→PROBLEM_RECOGNITION→PRODUCT_DESIRE→TRUST→ACTION)을 평가한다. "
    "냉정하게 점수를 매긴다(후하게 주지 않는다). 후기/평점/성능 같은 근거는 allowed_facts 에 있을 때만 trust 점수를 준다. "
    'JSON: {"scores":{"hook_strength","selling_point_clarity","purchase_motivation","trust_proof","cta_strength","retention","information_density","visual_selling_power"},'
    '"timeline":[{"scene_id","risk":"LOW|MEDIUM|HIGH","reason","viewer_thought","fix"}],'
    '"issues":[{"priority":"P0|P1|P2|P3","problem","cause","fix","effect","scene_id"}]}'
)


# ------------------------------------------------------------------ deterministic measurements
def _scenes(script: dict) -> list[dict]:
    return script["scenes"]


def measure(ctx: Ctx, state: dict, script: dict) -> dict:
    sc = _scenes(script)
    primary = state.get("primary_selling_point") or {}
    hook_sel = state.get("selected_hook") or {}
    cta_sel = (state.get("cta") or {}).get("selected") or {}
    narr = " ".join(s["narration"] for s in sc)
    total = max(script["estimated_seconds"], 0.1)
    reveal = next((s for s in sc if s["beat"] == "reveal"), None)
    reveal_at = reveal["time"][0] if reveal else None
    solution = [s for s in sc if s["scene_role"] == "SOLUTION" and s.get("feature")]
    proof = next((s for s in sc if s["scene_role"] == "PROOF" and s.get("kind") != "comment_trigger"), None)
    ptoks = tokens(f"{primary.get('text', '')} {primary.get('feature', '')}")
    ftoks = tokens(primary.get("feature") or "")
    ntoks = tokens(narr)
    cov_text = len(ptoks & ntoks) / len(ptoks) if ptoks else 0.0
    cov_feat = len(ftoks & ntoks) / len(ftoks) if ftoks else 0.0
    cov = max(min(1.0, cov_text * 1.6), cov_feat)           # 긴 문장형 구매 이유는 핵심 특징이 대본에 나오는지로 본다
    sims = [(a["scene_id"], b["scene_id"], jaccard(a["narration"], b["narration"])) for i, a in enumerate(sc) for b in sc[i + 1:]]
    repeats = [(a, b, round(s, 2)) for a, b, s in sims if s >= 0.6]
    cps = len(re.sub(r"\s+", "", narr)) / total
    blocks = [(s["scene_id"], i) for s in sc for i in line_issues(s["narration"] + " " + strip_marks(s["caption"]), ctx) if i["severity"] == "block"]
    claims_c = [(sid, i["detail"]) for sid, i in blocks if i["code"] not in ("cliche", "direct_comment")]
    style_bad = [(sid, i["detail"]) for sid, i in blocks if i["code"] in ("cliche", "direct_comment")]
    hook_blocks = [i for sid, i in blocks if sid == sc[0]["scene_id"]]
    problem_secs = sum(s["duration"] for s in sc if s["beat"] == "problem")
    real_proof = bool(proof and any(k in (proof.get("proof_source") or "") for k in ("review_quote", "my_take")))
    order_ok = (sc[0]["beat"] == "hook" and sc[-1]["beat"] == "cta" and (reveal is None or all(
        sc.index(s) > sc.index(reveal) for s in sc if s["beat"] in ("demo", "detail"))))
    return {"seconds": total, "reveal_at": reveal_at, "cps": round(cps, 2), "coverage": round(cov, 2), "repeats": repeats,
            "claims_c": claims_c, "style_bad": style_bad, "hook_blocks": len(hook_blocks),
            "hook_is_selected": narr.startswith(strip_marks(hook_sel.get("text", "\0"))), "problem_secs": round(problem_secs, 2), "solution_feature_scenes": len(solution),
            "hook_seconds": speak_seconds(sc[0]["narration"]), "real_proof": real_proof, "has_proof_scene": proof is not None,
            "filler": sum(len(FILLER.findall(s["narration"])) + len(PRAISE.findall(s["narration"])) for s in sc),
            "avg_scene": round(total / len(sc), 2), "order_ok": order_ok, "n_scenes": len(sc),
            "comment_scene": any(s.get("kind") == "comment_trigger" for s in sc),
            "hook_total": hook_sel.get("total"), "primary_total": primary.get("total"), "cta_total": cta_sel.get("total"),
            "cta_ad_resistance": (cta_sel.get("scores") or {}).get("ad_resistance")}


def det_scores(ctx: Ctx, m: dict, state: dict) -> dict:
    clamp = lambda v: int(max(0, min(100, round(v))))
    hook = m["hook_total"] if (m["hook_total"] is not None and m["hook_is_selected"]) else 55   # 대본의 실제 첫 문장이 선택한 Hook 과 다르면 다시 평가
    hook -= 28 * m["hook_blocks"]
    if m["hook_seconds"] > 3.5:
        hook = min(hook, 55)
    clarity = 35 + 65 * m["coverage"] - 10 * max(0, m["solution_feature_scenes"] - 2)
    motivation = 0.5 * (m["primary_total"] or 50) + 0.3 * (m["cta_total"] or 50) + (12 if ctx.p.problem else 0) + (6 if ctx.p.target else 0)
    trust = 30 + (30 if m["real_proof"] else 0) + (15 if ctx.has_clip else 0) + (10 if len(ctx.p.features) >= 2 else 0) + (5 if ctx.n_photos >= 3 else 0)
    if m["claims_c"]:
        trust = min(trust, 35)
    if not m["has_proof_scene"]:
        trust = min(trust, 40)
    cta = m["cta_total"] if m["cta_total"] is not None else 40
    retention = 100 - 14 * len(m["repeats"]) - (18 if (m["reveal_at"] or 0) > 5.0 else 0) - (12 if m["problem_secs"] > 4 else 0) \
        - (15 if m["avg_scene"] > 3.4 else 0) - (10 if m["avg_scene"] < 1.3 else 0) - (20 if not m["order_ok"] else 0) \
        - 5 * max(0, m["solution_feature_scenes"] - 2) + 5
    density = 100 - 16 * abs(m["cps"] - 5.2) - 8 * max(0, m["solution_feature_scenes"] - 2) - 4 * m["filler"]
    visual = 42 + 7 * min(4, ctx.n_photos) + (18 if ctx.has_clip else 0) + (6 if m["reveal_at"] is not None and m["reveal_at"] <= 4.5 else 0)
    return {k: clamp(v) for k, v in zip(METRICS, (hook, clarity, motivation, trust, cta, retention, density, visual))}


def timeline(ctx: Ctx, script: dict, m: dict, scores: dict) -> list[dict]:
    sc = _scenes(script)
    out, run = [], 0
    for i, s in enumerate(sc):
        risk, why, thought, fix, code = "LOW", "문제 없음", "", "", ""
        run = run + 1 if (s["scene_role"] == "SOLUTION" and s.get("feature")) else 0

        def bump(r, w, t, f, c):
            nonlocal risk, why, thought, fix, code
            if RISK_ORDER[r] > RISK_ORDER[risk]:
                risk, why, thought, fix, code = r, w, THOUGHT.get(t, t), f, c
        if s["beat"] == "hook" and (m["hook_seconds"] > 3.5 or scores["hook_strength"] < 60):
            bump("HIGH", f"Hook 이 {m['hook_seconds']}초 / 점수 {scores['hook_strength']}", "hook_long", "Hook 을 더 짧고 구체적으로", "hook_weak")
        if s["beat"] == "reveal" and (m["reveal_at"] or 0) > 5.0:
            bump("HIGH", f"제품 공개가 {m['reveal_at']}초에 등장", "late_reveal", "공개 전 장면을 줄이기", "late_reveal")
        if any(s["scene_id"] == b and jaccard(s["narration"], sc[[x["scene_id"] for x in sc].index(a)]["narration"]) >= 0.6 for a, b, _ in m["repeats"]):
            bump("HIGH", "앞 장면과 거의 같은 말", "repeat", "중복 장면 삭제", "repeat")
        if speak_seconds(s["narration"]) > 3.4:
            bump("MEDIUM", f"한 장면 대사가 {speak_seconds(s['narration'])}초", "long_line", "문장을 줄이기", "long_line")
        if s["beat"] == "problem" and ctx.p.target and not (tokens(s["narration"]) & tokens(f"{ctx.p.problem} {ctx.p.target}")):
            bump("MEDIUM", "대상/문제와 연결이 약함", "unrelated", "타겟의 실제 불편으로 교체", "unrelated")
        if run >= 3:
            bump("MEDIUM", "기능 설명이 3장면 연속", "enumeration", "가장 강한 기능 하나만 남기기", "enumeration")
        if s["beat"] == "cta" and (m["cta_ad_resistance"] or 100) < 55:
            bump("MEDIUM", "CTA 가 광고처럼 들림", "ad", "더 자연스러운 CTA 로 교체", "cta_ad")
        if s.get("kind") == "comment_trigger" and m["n_scenes"] >= 7:
            bump("MEDIUM", "CTA 직전 장면이 많아 흐름이 길어짐", "ad", "댓글 장치 삭제 검토", "comment_overload")
        out.append({"scene_id": s["scene_id"], "time": s["time"], "risk": risk, "reason": why, "viewer_thought": thought, "fix": fix, "code": code})
    return out


def issues_from(ctx: Ctx, m: dict, scores: dict, tl: list[dict]) -> list[dict]:
    I = []

    def add(pri, code, problem, cause, fix, effect, scene=None, op=None):
        I.append({"priority": pri, "code": code, "problem": problem, "cause": cause, "fix": fix, "effect": effect, "scene_id": scene, "op": op or code})
    if m["style_bad"]:
        add("P1", "cliche", f"상투구/직접 요구 표현: {m['style_bad'][0][1]}", "제품과 상관없이 쓸 수 있는 문구 또는 댓글 직접 요구", "제품 사실에 기반한 문장으로 교체",
            "광고 저항 감소", m["style_bad"][0][0], "fix_claims")
    if m["claims_c"]:
        add("P0", "unproven_claim", f"근거 없는 표현: {m['claims_c'][0][1]}", "입력에 없는 수치/성능/후기/희소성", "해당 문장을 사실만 말하는 문장으로 교체",
            "신뢰 하락과 규정 위험 제거", m["claims_c"][0][0], "fix_claims")
    if scores["hook_strength"] < GATE_MIN["hook_strength"] or m["hook_seconds"] > 3.5:
        add("P0", "hook_weak", f"Hook 점수 {scores['hook_strength']} / {m['hook_seconds']}초", "길거나 문제/타겟과 연결이 약함",
            "다른 Hook 후보로 교체", "첫 3초 이탈 감소", "S1", "swap_hook")
    if not m["order_ok"]:
        add("P0", "flow_break", "장면 순서가 흐름에 맞지 않음", "Hook 이 처음이 아니거나 CTA 가 마지막이 아니거나 공개 전에 데모", "순서 재배치", "흐름 단절 방지", None, "reorder")
    if scores["selling_point_clarity"] < GATE_MIN["selling_point_clarity"]:
        add("P1", "selling_diluted", f"핵심 구매 이유 전달 {scores['selling_point_clarity']}점",
            "핵심 구매 이유가 대본에 충분히 드러나지 않거나 기능이 분산됨", "핵심 기능 장면을 앞으로, 곁가지 기능 제거", "'그래서 뭐가 좋은데'를 한 번에 이해", None, "ensure_primary")
    if (m["reveal_at"] or 0) > 5.0:
        add("P1", "late_reveal", f"제품 공개가 {m['reveal_at']}초", "공개 전 장면이 김", "문제 장면 축소/삭제", "관심 유지", None, "shorten_intro")
    if m["repeats"]:
        a, b, s = m["repeats"][0]
        add("P1", "repeat", f"{a}와 {b}가 거의 같은 내용 (유사도 {s})", "같은 말을 두 번 함", "뒤 장면 삭제", "지루함 감소", b, "drop_repeat")
    if not m["has_proof_scene"] or (scores["trust_proof"] < 45 and (ctx.p.review_quotes or getattr(ctx.p, "my_take", ""))):
        add("P1", "no_proof", "Proof(신뢰 자료) 장면이 약함", "후기/직접 써본 느낌/시연 자료가 반영되지 않음", "입력된 후기·써본 느낌으로 Proof 교체", "신뢰 상승", None, "add_proof")
    if scores["cta_strength"] < GATE_MIN["cta_strength"] or (m["cta_ad_resistance"] or 100) < 55:
        add("P1", "cta_weak", f"CTA {scores['cta_strength']}점", "행동 유도가 약하거나 광고처럼 들림", "다른 CTA 후보로 교체", "행동 전환 상승", None, "swap_cta")
    if scores["information_density"] < GATE_MIN["information_density"]:
        add("P1", "info_overload", f"정보량 점수 {scores['information_density']} (말 속도 {m['cps']}자/초, 기능 장면 {m['solution_feature_scenes']}개)",
            "기능 나열 또는 말이 너무 빠름/느림", "곁가지 기능 장면 삭제", "이해도 상승", None, "focus")
    if m["solution_feature_scenes"] > 2:
        add("P2", "enumeration", f"기능 설명 장면 {m['solution_feature_scenes']}개", "한 영상에서 여러 장점을 설명", "가장 강한 기능 하나만 남김", "핵심 전달", None, "focus")
    if m["filler"]:
        add("P2", "filler", f"의미 없는 형용사/과한 칭찬 {m['filler']}개", "정말/진짜/최고 같은 말", "삭제", "신뢰 상승", None, "strip_filler")
    if m["problem_secs"] > 4:
        add("P2", "long_problem", f"문제 장면 {m['problem_secs']}초", "문제 설명이 김", "문장 단축", "이탈 감소", None, "shorten_intro")
    if m["comment_scene"] and m["n_scenes"] >= 7:
        add("P3", "comment_overload", "댓글 장치로 CTA 직전 흐름이 길어짐", "판매 흐름 방해 가능", "댓글 장치 삭제", "흐름 개선", None, "drop_comment")
    I.sort(key=lambda x: (x["priority"], x["code"]))
    return I


def gate(ctx: Ctx, m: dict, scores: dict) -> dict:
    fails = []

    def f(code, detail):
        fails.append({"code": code, "detail": detail})
    if scores["hook_strength"] < GATE_MIN["hook_strength"] or m["hook_seconds"] > 3.5:
        f("hook_below", f"Hook {scores['hook_strength']}점 / {m['hook_seconds']}초")
    if scores["selling_point_clarity"] < GATE_MIN["selling_point_clarity"] or m["coverage"] == 0:
        f("selling_point_unclear", f"핵심 구매 이유 전달 {scores['selling_point_clarity']}점")
    if m["claims_c"]:
        f("unproven_claim", f"근거 없는 표현 {len(m['claims_c'])}개: {m['claims_c'][0][1]}")
    if m["style_bad"]:
        f("hook_below" if m["hook_blocks"] else "cta_unnatural", f"상투구/직접 요구 표현: {m['style_bad'][0][1]}")
    if m["repeats"]:
        f("scene_repeat", f"반복 장면 {len(m['repeats'])}쌍")
    if scores["cta_strength"] < GATE_MIN["cta_strength"] or (m["cta_ad_resistance"] or 100) < 50:
        f("cta_unnatural", f"CTA {scores['cta_strength']}점")
    if scores["information_density"] < GATE_MIN["information_density"]:
        f("info_overload", f"정보량 {scores['information_density']}점")
    if scores["retention"] < GATE_MIN["retention"] or not m["order_ok"]:
        f("flow_break", f"유지력 {scores['retention']}점 / 순서 {'정상' if m['order_ok'] else '오류'}")
    if m["coverage"] < 0.3:
        f("product_story_disconnect", f"핵심 구매 이유가 대본에 {int(m['coverage'] * 100)}%만 반영")
    return {"passed": not fails, "failures": fails}


def removals(ctx: Ctx, script: dict, m: dict) -> list[dict]:
    sc = _scenes(script)
    out = []
    if m["filler"]:
        out.append({"type": "filler_words", "detail": f"의미 없는 형용사/칭찬 {m['filler']}개"})
    for a, b, s in m["repeats"]:
        out.append({"type": "duplicate_scene", "detail": f"{b} ≈ {a} (유사도 {s})", "scene_id": b})
    if m["solution_feature_scenes"] > 2:
        out.append({"type": "feature_list", "detail": f"기능 장면 {m['solution_feature_scenes']}개 중 곁가지 삭제"})
    if m["comment_scene"] and m["n_scenes"] >= 7:
        out.append({"type": "comment_overload", "detail": "댓글 장치"})
    for s, d in m["claims_c"] + m["style_bad"]:
        out.append({"type": "unproven_claim", "detail": d, "scene_id": s})
    return out


def run(router, ctx: Ctx, state: dict, script: dict) -> dict:
    m = measure(ctx, state, script)
    det = det_scores(ctx, m, state)
    scores, basis, llm_issues, llm_tl, llm_scores = dict(det), "rule", [], {}, {}
    raw = ask(router, SYSTEM, {**ctx.brief(), "script": [{k: s[k] for k in ("scene_id", "scene_role", "time", "narration", "caption", "product_visibility")} for s in _scenes(script)],
                               "measurements": {k: m[k] for k in ("seconds", "reveal_at", "cps", "hook_seconds", "solution_feature_scenes", "real_proof")}}, temperature=0.2)
    if raw and isinstance(raw.get("scores"), dict):
        # 게이트/자동 수정에 쓰는 점수는 '측정 가능한 규칙 점수'만 (LLM 점수는 실행마다 크게 흔들려 재현 불가). LLM 점수는 참고용으로 따로 보여준다.
        basis = "rule(+llm 참고)"
        llm_scores = {k: int(num(v)) for k, v in scale_scores(raw["scores"]).items() if k in METRICS}
        llm_tl = {t.get("scene_id"): t for t in (raw.get("timeline") or []) if isinstance(t, dict)}
        llm_issues = [i for i in (raw.get("issues") or []) if isinstance(i, dict) and i.get("problem")]
    tl = timeline(ctx, script, m, scores)
    for t in tl:                                           # LLM 은 더 높은 위험만 반영 (보수적), 시청자 생각 문장은 LLM 것을 우선
        l = llm_tl.get(t["scene_id"])
        if l and l.get("risk") in RISK_ORDER:
            if RISK_ORDER[l["risk"]] > RISK_ORDER[t["risk"]]:
                t.update({"risk": l["risk"], "reason": str(l.get("reason", t["reason"])), "fix": str(l.get("fix", "")), "code": t["code"] or "llm"})
            if l.get("viewer_thought") and t["risk"] != "LOW":
                t["viewer_thought"] = str(l["viewer_thought"])
    issues = issues_from(ctx, m, scores, tl)
    for i in llm_issues[:3]:
        pri = i.get("priority") if i.get("priority") in ("P0", "P1", "P2", "P3") else "P2"
        pri = {"P0": "P1"}.get(pri, pri)                    # 검증되지 않은 LLM 의견은 P0 로 올리지 않는다
        issues.append({"priority": pri, "source": "llm", "code": "llm_note", "problem": str(i.get("problem")), "cause": str(i.get("cause", "")), "fix": str(i.get("fix", "")),
                       "effect": str(i.get("effect", "")), "scene_id": i.get("scene_id"), "op": "none"})
    issues.sort(key=lambda x: (x["priority"], x["code"] == "llm_note", x["code"]))   # 같은 우선순위에서는 측정된 문제가 먼저
    funnel = {"SCROLL_STOP": scores["hook_strength"], "ATTENTION": round((scores["hook_strength"] + scores["retention"]) / 2),
              "INTEREST": scores["selling_point_clarity"],
              "PROBLEM_RECOGNITION": 78 if ctx.p.problem and any(s["beat"] == "problem" or jaccard(s["narration"], ctx.p.problem) > 0.4 for s in _scenes(script)) else 45,
              "PRODUCT_DESIRE": scores["purchase_motivation"], "TRUST": scores["trust_proof"], "ACTION": scores["cta_strength"]}
    g = gate(ctx, m, scores)
    return {"basis": basis, "scores": scores, "llm_scores": llm_scores, "overall": round(sum(scores.values()) / len(scores), 1), "funnel": funnel,
            "timeline": tl, "issues": issues, "top_fixes": ([i for i in issues if i["op"] != "none"] + [i for i in issues if i["op"] == "none"])[:5], "removals": removals(ctx, script, m), "measurements": m, "gate": g,
            "high_risk": [t for t in tl if t["risk"] == "HIGH"]}
