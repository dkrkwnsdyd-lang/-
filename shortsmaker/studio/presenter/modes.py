"""출연 방식(ACTOR MODE) 과 AUTO 선택, AI 장면 계획(plan).

PRODUCT_ONLY   : 상품 사진/B-roll/자막/TTS 만 (기본, 가장 저렴). 업로드한 사람 영상도 쓰지 않는다.
REAL_UGC       : 사용자가 찍은 사람/사용 영상 (AI 생성 비용 없음)
AI_PRESENTER   : AI 진행자가 카메라를 보며 설명 (Hook/CTA 위주, 20초 중 약 3~6초)
AI_PRODUCT_UGC : AI 인물이 제품을 들고/쓰는 장면 (비용·상품 왜곡 위험 -> 선택적, 상품 일치 검사 필수)
AUTO           : 1순위 실제 영상 > 2순위 AI 진행자 > 3순위 AI 제품 사용 > 4순위 제품만. 비용 드는 AI 는 최소화.

계획은 '무엇을 AI 로 만들지'만 정한다. API 호출(비용)은 사용자가 [AI 장면 생성]/[영상 제작]에서 동의한 뒤에만 한다.
"""
from __future__ import annotations

from . import cost as cost_mod
from . import real as real_mod
from .safety import presenter_problems, safe_line

ACTOR_MODES = ("PRODUCT_ONLY", "REAL_UGC", "AI_PRESENTER", "AI_PRODUCT_UGC", "AUTO")
ACTOR_KO = {"PRODUCT_ONLY": "제품만", "REAL_UGC": "실제 사람 영상", "AI_PRESENTER": "AI 아바타", "AI_PRODUCT_UGC": "AI 제품사용 UGC", "AUTO": "자동 선택"}
SOURCE_BADGE = {"": "ORIGINAL", "PRODUCT_IMAGE": "ORIGINAL", "PRODUCT_VIDEO": "REAL VIDEO", "REAL_UGC": "REAL VIDEO", "AI_PRESENTER": "AI PRESENTER",
                "AI_PRODUCT_UGC": "AI UGC", "BROLL": "B-ROLL", "TEXT_ONLY": "TEXT"}
USAGE_CATEGORIES = {"kitchen", "fitness", "camping", "beauty", "living"}       # 사용 장면을 보여주는 것이 판매에 중요한 카테고리(일반적 경향)


def uses_real_clips(actor_mode: str) -> bool:
    """업로드한 영상을 쓰는 모드 (PRODUCT_ONLY 와 AI 전용 모드는 쓰지 않는다)."""
    return actor_mode in ("REAL_UGC", "AUTO")


def effective_cost_mode(actor_mode: str, cost_mode: str) -> tuple[str, str]:
    """ECONOMY 에서는 AI 생성이 없다. 명시적으로 AI 모드를 골랐어도 그대로 두고 이유를 알려준다."""
    if cost_mode == "ECONOMY" and actor_mode in ("AI_PRESENTER", "AI_PRODUCT_UGC"):
        return "ECONOMY", "ECONOMY 비용 모드에서는 AI 영상을 만들지 않아요 (제품 사진으로 대체)"
    return cost_mode, ""


def _prompt(kind: str, ctx, scene) -> str:
    name = ctx.p.name
    if kind == "AI_PRESENTER":
        return (f"A friendly Korean presenter speaks directly to the camera, natural expression and gestures, casual clean background, 9:16 vertical, "
                f"{cost_mod.CLIP_SECONDS[kind]:.0f} seconds. The presenter holds NO product and shows NO logos, text overlays or brand marks. "
                f"Topic context (do not render as text): {name}.")
    feat = ctx.p.features[0] if ctx.p.features else ""
    return (f"A person naturally uses the product '{name}' in an everyday setting, 9:16 vertical, {cost_mod.CLIP_SECONDS[kind]:.0f} seconds. "
            f"The product must be IDENTICAL to the reference image: same shape, proportions, color, logo, printed text, button positions, parts. "
            f"{('Keep this feature clearly visible: ' + feat + '. ') if feat else ''}No extra logos or text, no product redesign, one slow camera movement.")


def _candidates(actor_mode: str, ctx, scenes: list, style: str, cost_mode: str, real_placed: bool) -> list[tuple]:
    """(scene, kind) 우선순위 목록."""
    hook = next((s for s in scenes if s.scene_type == "HOOK"), None)
    demo = next((s for s in scenes if s.scene_type == "DEMO"), None) or next((s for s in scenes if s.scene_type == "FEATURE"), None)
    cta = scenes[-1] if scenes and scenes[-1].scene_type == "CTA" else None
    out: list[tuple] = []
    premium = cost_mode == "PREMIUM"
    if actor_mode == "AI_PRESENTER":
        out += [(hook, "AI_PRESENTER")] + ([(cta, "AI_PRESENTER")] if premium else [])
    elif actor_mode == "AI_PRODUCT_UGC":
        out += [(demo, "AI_PRODUCT_UGC")] + ([(next((s for s in scenes if s.scene_type == "BENEFIT"), None), "AI_PRODUCT_UGC")] if premium else [])
    elif actor_mode == "AUTO":
        if real_placed:                                              # 1순위: 실제 영상이 있으면 AI 는 PREMIUM 에서 진행자 Hook 만
            out += [(hook, "AI_PRESENTER")] if premium else []
        else:
            presenter_fit = style in ("STORY_AD", "UGC_REVIEW")      # 2순위: 사람이 말하는 장면이 효과적인 스타일
            usage_fit = ctx.category in USAGE_CATEGORIES or (demo is not None and demo.visual_source.get("gap") == "usage_scene_missing")
            if presenter_fit:
                out.append((hook, "AI_PRESENTER"))
            if usage_fit:                                            # 3순위: 제품 사용 모습이 판매에 중요
                out.append((demo, "AI_PRODUCT_UGC"))
            if premium and cta is not None and presenter_fit:
                out.append((cta, "AI_PRESENTER"))
    return [(s, k) for s, k in out if s is not None]


def plan_production(scenes: list, *, ctx, actor_mode: str, cost_mode: str, style: str, infos: list[dict], router=None,
                    work_dir=None, reference_image: str | None = None) -> dict:
    """장면에 source_type 을 정한다. REAL_UGC 는 바로 배치(비용 0), AI 는 PLANNED 로 표시만 (호출 없음). 요약 dict 반환."""
    notes: list[str] = []
    actor_mode = actor_mode if actor_mode in ACTOR_MODES else "AUTO"
    cost_eff, why = effective_cost_mode(actor_mode, cost_mode)
    if why:
        notes.append(why)
    total = sum(s.duration for s in scenes)
    cap = cost_mod.ai_seconds_cap(cost_eff, total)
    summary = {"actor_mode": actor_mode, "cost_mode": cost_eff, "requested_cost_mode": cost_mode, "ai_seconds_cap": cap, "real_scenes": [], "ai_scenes": [],
               "notes": notes}
    real_report: list[dict] = []
    if uses_real_clips(actor_mode):
        real_report = real_mod.place(scenes, infos, router, work_dir)
        summary["real_scenes"] = real_report
        if actor_mode == "REAL_UGC" and not real_report:
            notes.append("쓸 수 있는 실제 사람/사용 영상이 없어 제품 사진으로 만들어요 (REAL_UGC → PRODUCT_ONLY)")
    elif infos:
        notes.append("업로드한 영상은 이 출연 방식에서는 사용하지 않아요")
    cands = _candidates(actor_mode, ctx, scenes, style, cost_eff, bool(real_report))
    used = 0.0
    n = 0
    for sc, kind in cands:
        secs = cost_mod.CLIP_SECONDS[kind]
        if n >= cost_mod.MAX_CLIPS[cost_eff] or used + secs > cap + 1e-6:
            notes.append(f"{sc.scene_id}({kind}): AI 영상 길이/개수 상한({cost_eff}: 최대 {cap:g}초, {cost_mod.MAX_CLIPS[cost_eff]}개)에 걸려 제외")
            continue
        if sc.source_type == "REAL_UGC" or sc.ai:
            continue
        fallback = sc.visual_source.get("fallback_path") or sc.visual_source.get("path") or reference_image
        sc.source_type = kind
        if kind == "AI_PRESENTER":                       # 진행자 대사는 가짜 사용 경험/근거 없는 주장 금지 (설명형)
            bad = presenter_problems(sc.narration, ctx)
            if bad:
                tts, cap_text = safe_line("CTA" if sc.scene_type == "CTA" else "HOOK", ctx, [f for f in ctx.p.features if f])
                notes.append(f"{sc.scene_id}: 진행자가 말하기 부적합한 문장({bad[0]['detail']}) → 설명형 문장으로 교체")
                sc.narration = tts
                sc.main_caption, sc.sub_caption = (cap_text.split("\n") + [""])[:2]
                sc.main_caption = sc.main_caption.replace("[[", "").replace("]]", "")
                sc.sub_caption = sc.sub_caption.replace("[[", "").replace("]]", "")
        ref = reference_image or fallback
        sc.layout = "lifestyle"
        sc.visual_source = {"kind": "ai_planned", "path": fallback, "tier": 6, "reason": "AI 생성 예정 - 생성 전에는 제품 사진으로 표시", "fallback_path": fallback}
        sc.ai = {"kind": kind, "status": "PLANNED", "provider": None, "model": None, "prompt": _prompt(kind, ctx, sc), "seconds": secs,
                 "cost": None, "retry_count": 0, "fidelity": None, "cache_key": None, "mock": False, "fallback_path": fallback, "reference_image": ref}
        sc.decisions["source"] = f"{kind} (AI 생성 예정, 아직 호출 안 함)"
        used += secs
        n += 1
        summary["ai_scenes"].append({"scene_id": sc.scene_id, "kind": kind, "seconds": secs})
    summary["ai_seconds"] = round(used, 1)
    if actor_mode == "AUTO" and not real_report and not summary["ai_scenes"]:
        notes.append("AUTO: 실제 영상이 없고 AI 장면이 꼭 필요하지 않아 제품만으로 구성")
    summary["effective_actor"] = ("REAL_UGC" if real_report else "") + ("+" if real_report and summary["ai_scenes"] else "") + \
        "+".join(sorted({a["kind"] for a in summary["ai_scenes"]})) or "PRODUCT_ONLY"
    return summary
