"""SHOPPING_SHORTS_STRATEGY_ENGINE 오케스트레이터.

PRODUCT ANALYSIS -> 1 SELLING POINT -> 2 ANGLE -> 3 HOOK -> 4 SCRIPT -> 5 COMMENT -> 6 CTA -> 7 CONVERSION AUDIT(+AUTO REVISION) -> FINAL SCRIPT
각 단계 결과는 state(JSON)에 저장하고, 앞 단계가 이미 있으면 다시 만들지 않는다 (start 이후만 재생성).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..storyboard.schema import Storyboard
from . import angles, audit, comment, cta, hooks, revise, script, selling
from .common import Ctx, STYLE_KO, grade, strip_marks

STAGES = ("selling_point", "angle", "hook", "script", "comment", "cta", "audit")
STATE_VERSION = 1
MAX_ROUNDS = 2
STORY_PATTERN = {"FAST_COMMERCE": "DEMONSTRATION", "STORY_AD": "PROBLEM_SOLUTION", "UGC_REVIEW": "DISCOVERY"}


def _snapshot(s: dict) -> dict:
    sc = s["scenes"]
    reveal = next((x for x in sc if x["beat"] == "reveal"), None)
    proof = next((x for x in sc if x["scene_role"] == "PROOF" and x.get("kind") != "comment_trigger"), None)
    return {"hook": sc[0]["narration"], "product_reveal": {"time": reveal["time"][0], "text": reveal["narration"]} if reveal else None,
            "proof": proof["narration"] if proof else None, "cta": sc[-1]["narration"], "scene_count": len(sc),
            "seconds": s["estimated_seconds"], "flow": [x["beat"] for x in sc]}


def _rebuild_draft(ctx: Ctx, state: dict) -> dict:
    d = copy.deepcopy(state["script"])
    d = comment.apply(d, state["comment_trigger"])
    return cta.apply(d, state["cta"])


def _audit_and_revise(router, ctx: Ctx, state: dict, auto: bool) -> None:
    draft = _rebuild_draft(ctx, state)
    state["draft_script"] = draft
    au = audit.run(router, ctx, state, draft)
    before = {"snapshot": _snapshot(draft), "scores": au["scores"], "overall": au["overall"]}
    rounds, cur = [], draft
    if auto:
        for r in range(1, MAX_ROUNDS + 1):
            blocking = [i for i in au["issues"] if i["priority"] in ("P0", "P1") and i["op"] != "none"]
            if au["gate"]["passed"] and not blocking:
                break
            ops = [i for i in au["top_fixes"] if i["op"] != "none"] or blocking
            if not ops:
                break
            cur2, log = revise.apply(router, ctx, state, cur, ops)
            if not log:
                break
            cur = cur2
            prev = au
            au = audit.run(router, ctx, state, cur)
            rounds.append({"round": r, "applied": log, "scores_before": prev["scores"], "scores_after": au["scores"],
                           "gate_passed": au["gate"]["passed"]})
    state["conversion_audit"] = {**au, "auto_revision": auto, "before": before, "rounds": rounds}
    state["final_script"] = {**cur, "revised": bool(rounds)}
    state["before_after"] = {"BEFORE": before["snapshot"], "AFTER": _snapshot(cur)}
    state["gate"] = au["gate"]


def run_strategy(router, ctx: Ctx, state: dict | None = None, start: str = "selling_point", picks: dict | None = None,
                 auto: bool = True, progress=None) -> dict:
    st = copy.deepcopy(state) if state else {}
    st.setdefault("version", STATE_VERSION)
    st["style"], st["style_ko"], st["auto"] = ctx.style, STYLE_KO[ctx.style], auto
    st["picks"] = {**(st.get("picks") or {}), **(picks or {})}
    si = STAGES.index(start)
    need = {"selling_point": "primary_selling_point", "angle": "selected_angle", "hook": "selected_hook", "script": "script",
            "comment": "comment_trigger", "cta": "cta"}
    for i, name in enumerate(STAGES):                              # 앞 단계 결과가 없으면 거기서부터 다시
        if i < si and name in need and need[name] not in st:
            si = i
            break
    bases = st.setdefault("basis", {})

    def say(msg):
        if progress:
            progress(msg)
    pk = st["picks"]
    if si <= 0:
        say("전략 1/7 핵심 구매 이유 분석")
        r = selling.run(router, ctx, pk)
        st.update({"selling_point_analysis": r, "product_analysis": r["product_analysis"], "primary_selling_point": r["primary"]})
        bases["selling_point"] = r["basis"]
    if si <= 1:
        say("전략 2/7 차별화 Angle")
        r = angles.run(router, ctx, st["primary_selling_point"], pk)
        st.update({"angle_analysis": r, "differentiation_angles": r["angles"], "selected_angle": r["selected"], "alternative_angle": r["alternative"],
                   "category_patterns": r["common_patterns"]})
        bases["angle"] = r["basis"]
    if si <= 2:
        say("전략 3/7 Hook 생성")
        r = hooks.run(router, ctx, st["primary_selling_point"], st["selected_angle"], st.get("product_analysis"), pk)
        st.update({"hook_analysis": r, "hook_candidates": r["candidates"], "selected_hook": r["selected"]})
        bases["hook"] = r["basis"]
    if si <= 3:
        say("전략 4/7 판매 대본")
        r = script.run(router, ctx, st["primary_selling_point"], st["selected_angle"], st["selected_hook"], pk)
        st["script"] = r
        bases["script"] = r["basis"]
    if si <= 4:
        say("전략 5/7 댓글 유도 장치")
        r = comment.run(router, ctx, st["script"], pk)
        st["comment_trigger"] = r
        bases["comment"] = r["basis"]
    if si <= 5:
        say("전략 6/7 CTA")
        r = cta.run(router, ctx, st["primary_selling_point"], comment.apply(copy.deepcopy(st["script"]), st["comment_trigger"]), pk)
        st["cta"] = r
        bases["cta"] = r["basis"]
    say("전략 7/7 전환 점검 + 자동 수정")
    _audit_and_revise(router, ctx, st, auto)
    bases["audit"] = st["conversion_audit"]["basis"]
    return st


# ------------------------------------------------------------------ 기존 파이프라인 연결
def to_director_data(ctx: Ctx, state: dict) -> dict:
    """기존 direct_scenes 가 받는 형식(beats/hook_candidates/...)으로 변환. Renderer/Storyboard 는 그대로 쓴다."""
    from ..director import selling_angles
    fs = state["final_script"]
    legacy = selling_angles(ctx.p)
    hooks_ = [state["selected_hook"]] + [h for h in state["hook_candidates"] if h["text"] != state["selected_hook"]["text"]][:2] if state.get("selected_hook") else []
    p = ctx.p
    return {"angles": legacy, "best_angle": legacy[0]["angle"],
            "story_pattern": STORY_PATTERN[ctx.style] if (p.problem or ctx.style != "STORY_AD") else "DISCOVERY",
            "hook_candidates": [{"type": f"strategy_{h['type'].lower()}", "text": h["text"], "caption": h["caption"]} for h in hooks_],
            "beats": [{"beat": s["beat"], "tts_line": s["tts_line"], "caption": s["caption"], "feature": s.get("feature") or None}
                      for s in fs["scenes"]],
            "tension": (state.get("primary_selling_point") or {}).get("text", ""), "payoff": (state.get("selected_angle") or {}).get("premise", ""),
            "_director": f"strategy_engine:{'/'.join(sorted(set(state.get('basis', {}).values())))}",
            "_grounding": {"final": "strategy_engine", "gate": state.get("gate")}}


def annotate_storyboard(sb: Storyboard, state: dict) -> None:
    """최종 Storyboard 장면에 scene_role/product_visibility 를 붙인다 (대사 일치로 매칭)."""
    by = {s["narration"]: s for s in state["final_script"]["scenes"]}
    for s in sb.scenes:
        m = by.get(s.narration)
        if m:
            s.scene_role, s.product_visibility = m["scene_role"], m["product_visibility"]


def final_storyboard_view(sb: Storyboard) -> list[dict]:
    out, t = [], 0.0
    for s in sb.scenes:
        out.append({"scene_id": s.scene_id, "time": [round(t, 2), round(t + s.duration, 2)], "scene_role": getattr(s, "scene_role", ""),
                    "purpose": s.purpose, "narration": s.narration, "caption": " / ".join(x for x in (s.main_caption, s.sub_caption) if x),
                    "visual_source": s.visual_source.get("kind"), "visual_prompt": s.visual_prompt, "layout": s.layout, "motion": s.image_motion,
                    "transition": s.transition, "sfx": [e.get("sfx") for e in s.sound_effect], "product_visibility": getattr(s, "product_visibility", "")})
        t += s.duration
    return out


def save_state(out_dir: Path, state: dict) -> None:
    d = Path(out_dir) / "strategy"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def pick(state: dict, stage: str, item_id: str) -> str:
    """사용자가 후보를 직접 고르면 저장된 후보에서 선택만 바꾸고(다시 생성하지 않음), 그 다음 단계부터 다시 계산한다. 반환: 다시 시작할 단계."""
    def find(items, key="id"):
        it = next((x for x in items or [] if x.get(key) == item_id), None)
        if it is None:
            raise ValueError(f"'{item_id}' 후보를 찾을 수 없어요")
        return it
    if stage == "selling_point":
        c = find(state["selling_point_analysis"]["candidates"])
        if c["reliability"] == "C":
            raise ValueError("입력에 근거가 없는 구매 이유(확인 불가)는 대표로 쓸 수 없어요")
        state["primary_selling_point"] = c
        state["selling_point_analysis"]["primary"] = c
        return "angle"
    if stage == "angle":
        first, second = angles.select_two(state["differentiation_angles"], item_id)
        state["selected_angle"], state["alternative_angle"] = first, second
        return "hook"
    if stage == "hook":
        state["selected_hook"] = find(state["hook_candidates"])
        return "script"
    if stage == "comment":
        c = find(state["comment_trigger"]["candidates"])
        state["comment_trigger"]["selected"], state["comment_trigger"]["method"] = c, c["method"]
        return "cta"
    if stage == "cta":
        state["cta"]["selected"] = find(state["cta"]["candidates"])
        return "audit"
    raise ValueError("선택할 수 없는 단계예요")
