"""AUTO REVISION: Conversion Audit 의 상위 문제를 결정적 연산으로 고친다 (추가보다 삭제 우선).

연산은 모두 '입력된 사실' 안에서만 문장을 바꾼다: 규칙 기반 문장(script.rule_beats)으로 교체하거나, STEP 3/6 에서 이미 검증된 후보로 교체하거나, 삭제한다.
"""
from __future__ import annotations

import copy
import re

from . import comment as comment_mod
from . import script as script_mod
from .common import FILLER, PRAISE, Ctx, jaccard, line_issues, make_caption, speak_seconds, strip_marks

ORDER = ["hook", "problem", "reveal", "demo", "detail", "benefit", "cta"]
CORE = {"hook", "reveal", "cta"}


def _rule(ctx: Ctx, state: dict) -> dict:
    return {b["beat"]: b for b in script_mod.rule_beats(ctx, state.get("primary_selling_point"), state.get("selected_hook"))}


def _set(s: dict, tts: str, cap: str, ctx: Ctx):
    from .common import grade
    s["tts_line"], s["narration"], s["caption"] = tts, strip_marks(tts), cap
    s["reliability"] = grade(tts + " " + cap, ctx)


def _drop(sc: list[dict], sid: str, log: list, why: str):
    for i, s in enumerate(sc):
        if s["scene_id"] == sid and s["beat"] not in CORE:
            log.append({"op": "drop_scene", "scene_id": sid, "before": s["narration"], "after": "(삭제)", "why": why})
            del sc[i]
            return True
    return False


def apply(router, ctx: Ctx, state: dict, script: dict, issues: list[dict]) -> tuple[dict, list[dict]]:
    script = copy.deepcopy(script)
    sc, log = script["scenes"], []
    done = set()
    rule = None
    for iss in issues:
        op = iss.get("op")
        if op in done or op in (None, "none"):
            continue
        done.add(op)
        if op == "fix_claims":
            rule = rule or _rule(ctx, state)
            for s in list(sc):
                bad = [i for i in line_issues(s["narration"] + " " + strip_marks(s["caption"]), ctx) if i["severity"] == "block"]
                if not bad:
                    continue
                fb = rule.get(s["beat"])
                if fb and not [i for i in line_issues(fb["tts_line"] + " " + strip_marks(fb["caption"]), ctx) if i["severity"] == "block"]:
                    log.append({"op": op, "scene_id": s["scene_id"], "before": s["narration"], "after": strip_marks(fb["tts_line"]), "why": bad[0]["detail"]})
                    _set(s, fb["tts_line"], fb["caption"], ctx)
                else:
                    _drop(sc, s["scene_id"], log, bad[0]["detail"])
        elif op == "swap_hook":
            cur = state.get("selected_hook") or {}
            alts = [h for h in sorted(state.get("hook_candidates") or [], key=lambda h: -h.get("style_fit", h["total"]))
                    if h["text"] != cur.get("text") and h["seconds"] <= 3.5 and h["total"] >= 60]
            if alts:
                h = alts[0]
                log.append({"op": op, "scene_id": sc[0]["scene_id"], "before": sc[0]["narration"], "after": h["text"], "why": f"Hook {cur.get('total')}점 → {h['total']}점 후보"})
                _set(sc[0], h["text"], h["caption"], ctx)
                state["selected_hook"] = h
        elif op == "reorder":
            sc.sort(key=lambda s: ORDER.index(s["beat"]))
            log.append({"op": op, "scene_id": "*", "before": "", "after": " → ".join(s["beat"] for s in sc), "why": "흐름 순서 보정"})
        elif op == "shorten_intro":
            prob = next((s for s in sc if s["beat"] == "problem"), None)
            if prob:
                _drop(sc, prob["scene_id"], log, "공개 전 장면이 길어 문제 장면 삭제 (Hook 이 이미 문제를 제시)")
        elif op == "drop_repeat":
            for a, b, _ in (issues and [(0, i.get("scene_id"), 0) for i in issues if i["op"] == "drop_repeat"]) or []:
                if not b:
                    continue
                if _drop(sc, b, log, "앞 장면과 중복"):
                    continue
                tgt = next((x for x in sc if x["scene_id"] == b), None)       # 삭제할 수 없는 핵심 장면(CTA)이면 덜 비슷한 다른 CTA 후보로 교체
                if tgt and tgt["beat"] == "cta":
                    others = " ".join(x["narration"] for x in sc if x is not tgt)
                    cands = [c for c in (state.get("cta") or {}).get("candidates", []) if c["text"] != tgt["tts_line"] and c["total"] >= 55
                             and jaccard(strip_marks(c["text"]), others) < 0.35]
                    if cands:
                        c = cands[0]
                        log.append({"op": op, "scene_id": tgt["scene_id"], "before": tgt["narration"], "after": strip_marks(c["text"]), "why": "앞 장면과 거의 같은 말이라 다른 CTA 로 교체"})
                        state["cta"]["selected"] = c
                        _set(tgt, c["text"], c["caption"], ctx)
        elif op == "ensure_primary":
            pf = (state.get("primary_selling_point") or {}).get("feature") or ""
            if pf and not any(pf == s.get("feature") for s in sc):
                from ..director import feature_lines
                tts, cap = feature_lines([pf])[0]
                tgt = next((s for s in sc if s["beat"] == "demo"), None) or next((s for s in sc if s["beat"] == "detail"), None)
                if tgt:
                    log.append({"op": op, "scene_id": tgt["scene_id"], "before": tgt["narration"], "after": strip_marks(tts), "why": "핵심 구매 이유(대표 특징)를 보여주는 장면으로 교체"})
                    _set(tgt, tts, cap, ctx)
                    tgt["feature"] = pf
        elif op == "focus":
            feats = [s for s in sc if s["scene_role"] == "SOLUTION" and s.get("feature")]
            if len(feats) > 2:
                primary_f = (state.get("primary_selling_point") or {}).get("feature") or ""
                rank = {c["feature"]: c["total"] for c in (state.get("selling_point_analysis") or {}).get("candidates", []) if c.get("feature")}
                keep = sorted(feats, key=lambda s: (s["feature"] != primary_f, -rank.get(s["feature"], 0)))[:2]
                for s in feats:
                    if s not in keep:
                        _drop(sc, s["scene_id"], log, "한 영상에서 기능을 모두 설명하지 않음 (핵심 기능만)")
        elif op == "add_proof":
            rule = rule or _rule(ctx, state)
            pr = next((s for s in sc if s["scene_role"] == "PROOF" and s.get("kind") != "comment_trigger"), None)
            fb = rule.get("benefit")
            if pr and fb and fb.get("proof_source", "").startswith(("review_quote", "my_take")):
                log.append({"op": op, "scene_id": pr["scene_id"], "before": pr["narration"], "after": strip_marks(fb["tts_line"]), "why": "입력된 후기/써본 느낌으로 Proof 교체"})
                _set(pr, fb["tts_line"], fb["caption"], ctx)
                pr["proof_source"] = fb["proof_source"]
        elif op == "swap_cta":
            from . import cta as cta_mod
            cur = ((state.get("cta") or {}).get("selected") or {})
            alts = [c for c in (state.get("cta") or {}).get("candidates", []) if c["text"] != cur.get("text") and c["total"] >= 55]
            if alts:
                c = alts[0]
                log.append({"op": op, "scene_id": sc[-1]["scene_id"], "before": sc[-1]["narration"], "after": strip_marks(c["text"]), "why": f"CTA {cur.get('total')}점 → {c['total']}점 후보"})
                state["cta"]["selected"] = c
                _set(sc[-1], c["text"], c["caption"], ctx)
        elif op == "strip_filler":
            for s in sc:
                new = re.sub(r"\s{2,}", " ", PRAISE.sub("", FILLER.sub("", s["tts_line"]))).strip()
                if new and new != s["tts_line"]:
                    log.append({"op": op, "scene_id": s["scene_id"], "before": s["narration"], "after": strip_marks(new), "why": "의미 없는 형용사/과한 칭찬 삭제"})
                    s["tts_line"], s["narration"] = new, strip_marks(new)
        elif op == "drop_comment":
            for s in list(sc):
                if s.get("kind") == "comment_trigger":
                    log.append({"op": op, "scene_id": s["scene_id"], "before": s["narration"], "after": "(삭제)", "why": "판매 흐름 우선"})
                    sc.remove(s)
                    (state.get("comment_trigger") or {})["insert"] = False
                    (state.get("comment_trigger") or {})["skip_reason"] = "Conversion Audit 에서 흐름 방해로 삭제"
    return comment_mod.renumber(script), log
