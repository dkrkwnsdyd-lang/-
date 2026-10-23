"""Preview 대본을 실제 렌더 계획 기준으로 재감사한다.

기존 Conversion Audit 결과를 재사용하면 사용자 편집이 감사되지 않은 채 게시될 수 있다.
승인 전에 렌더에 들어갈 대본/순서/삭제를 기존 rule-only 감사 엔진으로 재측정한다.
외부 LLM을 호출하지 않아도 수행되며 측정 한계를 결과에 명시한다.
"""
from __future__ import annotations

from copy import deepcopy

from . import audit

_TEXT_CHANGES = frozenset(("나레이션", "자막", "삭제", "순서 변경"))


def requires_recheck(report: dict) -> bool:
    return any(item.get("what") in _TEXT_CHANGES for item in (report.get("applied") or []))


def _blocked(state: dict, code: str, detail: str) -> dict:
    updated = deepcopy(state)
    updated["gate"] = {"passed": False, "failures": [{"code": code, "detail": detail}]}
    updated["preview_review"] = {
        "status": "BLOCKED", "basis": "rule", "reason": detail,
        "fact_verification": "not_run",
    }
    # Never show an old passing audit as the evaluation of the changed script.
    updated["conversion_audit"] = {"status": "STALE", "gate": updated["gate"]}
    return updated


def recheck_edited_plan(state: dict, plan, ctx) -> dict:
    """Return a new strategy state audited against the *actual* edited plan.

    Maps rendered scene IDs/beats to the original strategy script. When mapping
    cannot be trusted the output is blocked, not silently rated using old data.
    """
    original = (state.get("final_script") or {}).get("scenes") or []
    if not original or not plan.scenes:
        return _blocked(state, "audit_unavailable", "편집한 장면의 평가 원본이 없습니다")

    by_id = {s.get("scene_id"): s for s in original if s.get("scene_id")}
    used = set()
    rows = []
    offset = 0.0

    for sc in plan.scenes:
        source = by_id.get(sc.scene_id)
        idx = next((i for i, s in enumerate(original) if s is source), None) if source is not None else None
        if source is None or source.get("beat") != sc.beat or idx in used:
            # A compacted plan may change scene IDs. Recover only a unique
            # identical beat; ambiguous remaps require review.
            candidates = [(i, s) for i, s in enumerate(original)
                          if i not in used and s.get("beat") == sc.beat]
            if len(candidates) != 1:
                return _blocked(state, "audit_scene_mismatch",
                                f"{sc.scene_id}: 원본 장면을 확실하게 연결할 수 없습니다")
            idx, source = candidates[0]
        used.add(idx)
        if not source.get("scene_role"):
            return _blocked(state, "audit_scene_mismatch",
                            f"{sc.scene_id}: 평가할 장면 역할 정보가 없습니다")
        row = deepcopy(source)
        row.update(scene_id=sc.scene_id, beat=sc.beat, narration=sc.tts_line,
                   tts_line=sc.tts_line, caption=sc.caption,
                   duration=float(sc.duration),
                   time=[round(offset, 2), round(offset + sc.duration, 2)])
        offset += float(sc.duration)
        rows.append(row)

    revised_script = deepcopy(state["final_script"])
    revised_script["scenes"] = rows
    revised_script["estimated_seconds"] = round(offset, 2)
    # The deterministic audit is authoritative for gates. LLM subjective
    # opinion is not silently carried over and no paid API call is made here.
    outcome = audit.run(None, ctx, state, revised_script)
    reviewed = deepcopy(state)
    reviewed["final_script"] = revised_script
    reviewed["conversion_audit"] = {
        **outcome, "basis": "rule (edited preview)", "status": "RECHECKED",
        "auto_revision": False,
    }
    reviewed["gate"] = outcome["gate"]
    reviewed["preview_review"] = {
        "status": "RECHECKED", "basis": "rule", "scene_count": len(rows),
        "fact_verification": "rule_only; external source verification not performed",
        "passed": outcome["gate"]["passed"],
    }
    return reviewed
