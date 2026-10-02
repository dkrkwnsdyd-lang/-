"""PRODUCT ADAPTATION: 섞은 패턴(mixed) → 현재 상품용 '연출 가이드'(guide). 참고 영상의 내용이 아니라 구조(상황 구조/감정 흐름/공개 타이밍/템포/카메라)만 쓴다.

사실 안전: 상황/문제/감정/전환 단계는 현재 상품 입력(problem/target)에 근거가 있을 때만 장면이 된다. 근거가 없으면 그 단계를 빼고 이유를 warnings 에 남긴다
(참고 영상의 상황을 '지어내서' 가져오지 않는다). 성능/가격/후기/할인은 패턴에 저장되지 않으므로 가져올 수도 없다.
"""
from __future__ import annotations

from . import vocab

HOOK_TYPE = {"problem_first": "PROBLEM", "question": "CURIOSITY", "curiosity_gap": "CURIOSITY", "empathy": "EMPATHY", "pov": "EMPATHY", "direct_address": "PROBLEM",
             "demo_first": "CURIOSITY", "shock_visual": "CURIOSITY", "number_list": "CURIOSITY", "other": None}
CTA_STRATEGY = {"soft_recommendation": "DIRECT", "direct_link": "DIRECT", "scarcity": "SCARCITY", "question": "LOSS_AVERSION", "none": None}
MOTION_BIAS = {"punch_in": {"punch_in": 3.0, "zoom_in": 1.5}, "slow_zoom": {"slow_zoom": 3.0}, "ken_burns": {"ken_burns": 3.0}, "pan": {"pan_left": 2.5, "pan_right": 2.5},
               "parallax": {"parallax": 2.5, "depth_zoom": 1.5}, "handheld": {"shake": 1.5, "ken_burns": 1.5}, "static": {"slow_zoom": 1.0}, "fast_cut": {}}
TRANSITION_MAP = {"whip": {"PRODUCT_REVEAL": "whip", "FEATURE": "whip"}, "flash": {"PRODUCT_REVEAL": "flash", "CTA": "flash"},
                  "soft_dissolve": {"PROBLEM": "soft", "PRODUCT_REVEAL": "soft", "DEMO": "soft", "BENEFIT": "soft", "PROOF": "soft", "CTA": "soft"}, "hard_cut": {},
                  "match_cut": {"PRODUCT_REVEAL": "soft"}}
CAPTION_ZONE = {"short_center": "top", "top_keyword": "top", "short_bottom": "bottom", "dense_bottom": "bottom", "karaoke_word": "top", "none": "top"}
MAX_SCENES = 8


def stages_to_beats(stages: list[str], ctx, warnings: list[str]) -> list[tuple[str, str]]:
    """STORY 단계 → (기존 beat 이름, story_role). beat 는 director 의 hook/problem/reveal/demo/detail/benefit/cta."""
    has_problem = bool(ctx.p.problem.strip())
    evidence = bool(getattr(ctx.p, "my_take", "") or ctx.p.review_quotes or ctx.has_clip)
    out: list[tuple[str, str]] = []
    dropped = []
    for st in stages:
        if st == "hook":
            out.append(("hook", "hook"))
        elif st in ("situation", "problem", "emotion", "turning_point"):
            if not has_problem:
                dropped.append(st)
                continue
            if st == "situation":
                out.append(("problem", "situation"))
            elif st == "problem":
                out.append(("problem", "pain"))
            elif st == "emotion":
                if out and out[-1] == ("problem", "pain"):
                    out[-1] = ("problem", "pain_emotion")          # 감정은 문제 장면에 합친다 (장면 수 절약)
                else:
                    out.append(("problem", "pain_emotion"))
            # turning_point 는 reveal 장면의 전환 문구로 합쳐진다
        elif st == "product_reveal":
            tp = "turning" if "turning_point" in stages and has_problem else "reveal"
            out.append(("reveal", tp))
        elif st == "demo":
            out.append(("demo", "demo"))
        elif st == "benefit":
            out.append(("benefit", "result"))
        elif st == "proof":
            out.append(("benefit", "proof") if evidence else ("benefit", "result"))
        elif st == "cta":
            out.append(("cta", "cta"))
    if dropped:
        warnings.append(f"입력에 문제/상황 정보가 없어 {', '.join(sorted(set(dropped)))} 단계를 뺐어요 (참고 영상의 상황을 가져오지 않음)")
    # 정리: hook 처음, cta 마지막, 중복 연속 제거, reveal 보장
    seen_pairs = []
    for b in out:
        if seen_pairs and seen_pairs[-1] == b:
            continue
        seen_pairs.append(b)
    out = seen_pairs
    if not out or out[0][0] != "hook":
        out.insert(0, ("hook", "hook"))
    if not any(b == "reveal" for b, _ in out):
        out.insert(1 + sum(1 for b, _ in out if b == "problem"), ("reveal", "reveal"))
    if not any(b == "demo" for b, _ in out):                     # 제품의 핵심 특징을 보여주는 장면은 항상 필요 (참고 영상에 시연 단계가 없어도)
        out.append(("demo", "demo"))
    out = [b for b in out if b[0] != "cta"] + [("cta", "cta")]
    # reveal 은 모든 demo/benefit 앞
    order = {"hook": 0, "problem": 1, "reveal": 2, "demo": 3, "detail": 4, "benefit": 5, "cta": 6}
    out.sort(key=lambda b: order[b[0]])
    # 장면 수 상한: 곁가지부터 (두 번째 problem, benefit proof) 줄인다
    while len(out) > MAX_SCENES:
        for victim in (("problem", "pain_emotion"), ("problem", "pain"), ("problem", "situation"), ("benefit", "proof"), ("demo", "demo")):
            if victim in out and len(out) > MAX_SCENES:
                out.remove(victim)
        break
    return out[:MAX_SCENES]


def build_guide(mixed: dict, ctx, style: str | None = None) -> dict:
    """mixed(mix.mix 결과) → guide. ctx 는 strategy.common.Ctx."""
    v = mixed.get("values") or {}
    warnings: list[str] = []
    stages = v.get("story_stages") or []
    beats = stages_to_beats(stages, ctx, warnings) if stages else []
    n_pre = sum(1 for b, _ in beats if b in ("problem",))
    story_heavy = n_pre >= 2 or "emotion_curve" in v and v.get("emotion_curve") == "dip_then_rise"
    ctype = v.get("content_style")
    suggestion = "STORY_AD" if story_heavy or ctype == "story" else ("UGC_REVIEW" if ctype in ("ugc", "lifestyle") else "FAST_COMMERCE")
    avg = v.get("average_scene_duration")
    tempo = {"avg": max(1.2, min(3.6, float(avg))) if avg else None, "hook_max": max(1.2, min(3.0, float(v["hook_duration"]))) if v.get("hook_duration") else None}
    motions = list(dict.fromkeys((v.get("camera_motion") or []) + (v.get("image_motion") or [])))
    bias: dict[str, float] = {}
    for m in motions:
        for k, w in MOTION_BIAS.get(m, {}).items():
            bias[k] = max(bias.get(k, 0.0), w)
    trans = {}
    for t in v.get("transition_pattern") or []:
        trans.update(TRANSITION_MAP.get(t, {}))
    sfx = v.get("sfx_pattern")
    guide = {
        "version": 1, "sources": mixed.get("sources", []), "aspects": mixed.get("aspects", {}), "style_suggestion": suggestion,
        "hook": {"pattern": v.get("hook_pattern"), "type": HOOK_TYPE.get(v.get("hook_pattern") or "other"), "duration": tempo["hook_max"]},
        "story": {"stages": stages, "beat_plan": [{"beat": b, "role": r} for b, r in beats], "emotion_curve": v.get("emotion_curve"),
                  "roles": v.get("story_roles") or {}, "selling_structure": v.get("selling_structure")},
        "tempo": tempo, "reveal_target": v.get("product_reveal_time"),
        "caption": {"pattern": v.get("caption_pattern"), "density": v.get("caption_density"), "position": v.get("caption_position"), "zone": CAPTION_ZONE.get(v.get("caption_pattern") or "", None),
                    "change": v.get("caption_change_frequency")},
        "motion": {"patterns": motions, "bias": bias}, "transition": {"patterns": v.get("transition_pattern") or [], "map": trans},
        "sfx": {"pattern": sfx, "ratio": {"none": 0.2, "sparse": 0.45, "frequent": 0.8}.get(sfx)}, "bgm_mood": v.get("bgm_mood"),
        "cta": {"pattern": v.get("cta_pattern"), "strategy": CTA_STRATEGY.get(v.get("cta_pattern") or "none"), "position": v.get("cta_position")},
        "fingerprint": mixed.get("fingerprint", []), "warnings": warnings,
        "rules": ["참고 영상의 대사/문구/Hook/장면 배열을 복사하지 않는다", "상품 정보는 현재 Product Intelligence 만 사용", "외국어 직역체/과장 표현 금지"],
    }
    return guide


def shape_scenes(scenes: list, guide: dict) -> dict:
    """Storyboard 장면 길이/전환을 패턴 템포에 맞춘다 (평균 장면 길이, Hook 상한). 반환: 적용 요약."""
    applied = {}
    avg_t = (guide.get("tempo") or {}).get("avg")
    hook_max = (guide.get("tempo") or {}).get("hook_max")
    if avg_t and scenes:
        cur = sum(s.duration for s in scenes) / len(scenes)
        k = avg_t / cur if cur else 1.0
        for s in scenes:
            s.duration = round(max(1.1, min(4.2, s.duration * k)), 2)
        applied["tempo_scale"] = round(k, 2)
    if hook_max and scenes and scenes[0].scene_type == "HOOK":
        scenes[0].duration = round(min(scenes[0].duration, hook_max), 2)
        applied["hook_max"] = hook_max
    tmap = (guide.get("transition") or {}).get("map") or {}
    if tmap:
        for i, s in enumerate(scenes):
            if i and s.scene_type in tmap:
                s.transition = tmap[s.scene_type]
        applied["transition_map"] = tmap
    return applied


def report(sb, guide: dict) -> dict:
    """적용 결과 요약 (참고 패턴 vs 실제 Storyboard)."""
    t, reveal = 0.0, None
    for s in sb.scenes:
        if s.scene_type == "PRODUCT_REVEAL" and reveal is None:
            reveal = round(t, 2)
        t += s.duration
    n = len(sb.scenes)
    return {"scene_count": n, "avg_scene": round(t / n, 2) if n else 0, "reveal_time": reveal, "total": round(t, 2),
            "target_avg": (guide.get("tempo") or {}).get("avg"), "target_reveal": guide.get("reveal_target"),
            "beats": [{"scene_id": s.scene_id, "type": s.scene_type, "role": getattr(s, "story_role", "")} for s in sb.scenes]}
