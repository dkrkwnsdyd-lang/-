"""PREVIEW MODE: 스토리보드를 장면 카드로 먼저 보여주고, 사용자 수정(edits)을 안전하게 반영한다.

edits = {"order": ["S1", ...], "scenes": {"S3": {"narration", "caption", "layout", "motion", "transition",
                                                  "photo_index", "sfx", "drop"}}}
- 텍스트/순서/삭제는 '대본(plan)' 에, 연출(layout/motion/전환/사진/효과음)은 '스토리보드' 에 반영한다.
- 제품 사실을 해치는 수정은 거부한다: HOOK 은 맨 앞, CTA 는 맨 뒤, 사용할 수 없는 레이아웃(시연 영상 없는 demo 등)은 거부.
- 거부된 수정은 이유와 함께 돌려준다 (조용히 무시하지 않는다).
"""
from __future__ import annotations

from . import layouts as layout_engine
from . import motion_director, sfx_director
from .motion_director import MOTIONS
from .schema import Storyboard

TRANSITIONS = ("cut", "whip", "flash", "soft")
MAX_TEXT = 120


def _clean(s) -> str:
    return " ".join(str(s or "").split())[:MAX_TEXT]


def apply_plan_edits(plan, edits: dict | None) -> dict:
    """대본 수준 수정: 순서/삭제/나레이션/자막. {applied:[], rejected:[]}"""
    rep = {"applied": [], "rejected": []}
    if not edits:
        return rep
    by_id = {s.scene_id: s for s in plan.scenes}
    for sid, e in (edits.get("scenes") or {}).items():
        sc = by_id.get(sid)
        if sc is None:
            rep["rejected"].append({"scene_id": sid, "why": "없는 장면"})
            continue
        if e.get("drop"):
            if sc.beat in ("hook", "cta"):
                rep["rejected"].append({"scene_id": sid, "why": "훅/CTA 장면은 삭제할 수 없어요"})
            elif len(plan.scenes) <= 3:
                rep["rejected"].append({"scene_id": sid, "why": "장면이 너무 적어져요 (최소 3개)"})
            else:
                plan.scenes.remove(sc)
                rep["applied"].append({"scene_id": sid, "what": "삭제"})
            continue
        if "narration" in e and _clean(e["narration"]):
            sc.tts_line = _clean(e["narration"])
            rep["applied"].append({"scene_id": sid, "what": "나레이션"})
        if "caption" in e and _clean(e["caption"]):
            sc.caption = _clean(e["caption"])
            rep["applied"].append({"scene_id": sid, "what": "자막"})
    order = (edits or {}).get("order")
    if order:
        ids = [s.scene_id for s in plan.scenes]
        cur = {s.scene_id: s for s in plan.scenes}
        if sorted(order) != sorted(ids):
            rep["rejected"].append({"scene_id": "*", "why": "순서 목록이 현재 장면과 맞지 않아요"})
        elif cur[order[0]].beat != "hook" or cur[order[-1]].beat != "cta":
            rep["rejected"].append({"scene_id": "*", "why": "훅은 맨 앞, CTA는 맨 뒤에 있어야 해요"})
        elif order != ids:
            plan.scenes[:] = [cur[i] for i in order]
            rep["applied"].append({"scene_id": "*", "what": "순서 변경"})
    return rep


def options_for(scene, ctx) -> dict:
    """장면 카드에서 고를 수 있는 선택지 (사용할 수 없는 레이아웃은 이유와 함께 제외)."""
    lays = [l for l in layout_engine.LAYOUTS if layout_engine.availability(l, scene, ctx)[0]]
    return {"layouts": lays, "motions": sorted(motion_director.allowed_for(scene.layout)), "transitions": list(TRANSITIONS)}


def apply_sb_edits(sb: Storyboard, edits: dict | None, ctx, identity, features: list[str]) -> dict:
    rep = {"applied": [], "rejected": []}
    if not edits:
        return rep
    sfx_off: set[str] = set()
    changed = False
    for sid, e in (edits.get("scenes") or {}).items():
        sc = sb.scene(sid)
        if sc is None:
            continue                                  # 삭제되었거나 plan 단계에서 이미 보고됨
        if "photo_index" in e and e["photo_index"] is not None:
            try:
                ph = identity.photos[int(e["photo_index"])]
            except (ValueError, IndexError, TypeError):
                rep["rejected"].append({"scene_id": sid, "why": "없는 사진 번호"})
            else:
                sc.visual_source = {"kind": "user_photo", "path": ph["path"], "tier": 1, "reason": "사용자가 미리보기에서 교체"}
                if ph.get("product_box"):
                    sc.visual_source["box"] = list(ph["product_box"])
                rep["applied"].append({"scene_id": sid, "what": "이미지 교체"})
                changed = True
        if e.get("layout"):
            ok, why = layout_engine.availability(e["layout"], sc, ctx) if e["layout"] in layout_engine.LAYOUTS else (False, "없는 레이아웃")
            if ok:
                sc.layout = e["layout"]
                sc.decisions["layout"] = "사용자 선택 (미리보기)"
                if sc.image_motion not in motion_director.allowed_for(sc.layout):
                    sc.image_motion = "slow_zoom"      # 새 레이아웃에서 허용되지 않는 모션은 가장 안전한 값으로
                rep["applied"].append({"scene_id": sid, "what": f"레이아웃 {e['layout']}"})
                changed = True
            else:
                rep["rejected"].append({"scene_id": sid, "why": why})
        if e.get("motion"):
            if e["motion"] in MOTIONS and e["motion"] in motion_director.allowed_for(sc.layout):
                sc.image_motion = e["motion"]
                sc.decisions["motion"] = "사용자 선택 (미리보기)"
                rep["applied"].append({"scene_id": sid, "what": f"모션 {e['motion']}"})
                changed = True
            else:
                rep["rejected"].append({"scene_id": sid, "why": f"'{e['motion']}' 모션은 {sc.layout} 레이아웃에 맞지 않아요"})
        if e.get("transition") in TRANSITIONS:
            sc.transition = e["transition"]
            rep["applied"].append({"scene_id": sid, "what": f"전환 {e['transition']}"})
            changed = True
        if e.get("sfx") is False:
            sfx_off.add(sid)
        a = e.get("ai")
        if isinstance(a, dict) and sc.ai:                  # AI 장면 하나만 제어 (전체를 다시 만들지 않는다): 원본으로/재생성/프롬프트/Provider
            if a.get("action") == "revert":
                sc.ai["action"] = "revert"
                rep["applied"].append({"scene_id": sid, "what": "AI 장면을 원본으로"})
            if a.get("action") == "regenerate":
                sc.ai["force"] = True
                rep["applied"].append({"scene_id": sid, "what": "AI 장면 재생성 요청"})
            if a.get("prompt"):
                sc.ai["prompt_override"] = " ".join(str(a["prompt"]).split())[:800]
                rep["applied"].append({"scene_id": sid, "what": "AI 프롬프트 수정"})
            if a.get("provider"):
                sc.ai["provider_pref"] = str(a["provider"])[:30]
                rep["applied"].append({"scene_id": sid, "what": f"Provider {a['provider']}"})
    if changed:
        sb.scenes[0].transition = "cut"
        from .styles import profile
        sp = profile(sb.style)["sfx"]
        sfx_director.direct_sfx(sb.scenes, ratio=sp["ratio"], heavy=sp["heavy"])             # 레이아웃/모션이 바뀌면 효과음 위치도 다시 계산
    for sid in sfx_off:
        sb.scene(sid).sound_effect = []
        rep["applied"].append({"scene_id": sid, "what": "효과음 끔"})
    from . import validator
    sb.issues = validator.validate(sb.scenes, features, fix=False)    # 사용자가 고른 것은 덮어쓰지 않고 경고만
    return rep
