"""STORYBOARD ENGINE - 대본(CreativePlan)을 영상 길이에 맞는 Storyboard(JSON)로 바꾼다.

상품 분석 → 판매각 → Hook → Script → [Storyboard] → Scene Director → Preview → Render
기존 director/editor/renderer 는 그대로 두고, 그 사이에 끼워 넣는다.
"""
from __future__ import annotations

from .. import grounding
from . import layouts as layout_engine
from . import motion_director
from . import validator
from . import sfx_director
from . import styles
from .scene_director import SceneDirector
from .schema import Storyboard, duration_class

# 장면 수를 줄여야 할 때 먼저 버리는 순서 (HOOK/PRODUCT_REVEAL/CTA 와 첫 DEMO/BENEFIT 은 보존)
DROP_ORDER = ("PROOF", "FEATURE", "PROBLEM", "DEMO", "BENEFIT")
KEEP_FIRST = {"HOOK", "PRODUCT_REVEAL", "CTA"}
MUSIC_BY_STYLE = {"STANDARD": "clean, upbeat, instrumental, ~100 BPM, 첫 박부터 시작",
                  "FAST_COMMERCE": "energetic, tight drums, ~120 BPM", "PREMIUM": "soft, warm, slow build, ~80 BPM",
                  "UGC_REVIEW": "light acoustic, natural, low volume", "STORY_AD": "cinematic, gentle build, emotional turn"}


def fit_scene_count(scenes: list, rng: tuple[int, int], warnings: list[str]) -> list:
    """권장 장면 수 상한을 넘으면 우선순위가 낮은 장면부터 줄인다. 부족하면 억지로 늘리지 않고 경고만."""
    lo, hi = rng
    scenes = list(scenes)
    while len(scenes) > hi:
        victim = None
        for t in DROP_ORDER:
            same = [s for s in scenes if s.scene_type == t]
            if t in ("DEMO", "BENEFIT"):
                same = same[1:]                                   # 첫 번째는 보존
            elif t == "FEATURE":
                same = same[1:] if len(same) > 1 else []          # 대표 특징 1개는 보존
            if same:
                victim = same[-1]
                break
        if victim is None:
            break
        scenes.remove(victim)
        warnings.append(f"권장 장면 수({lo}~{hi}) 초과로 {victim.scene_id}({victim.scene_type}) 제외")
    if len(scenes) < lo:
        warnings.append(f"장면이 {len(scenes)}개로 권장({lo}~{hi})보다 적어요. 같은 내용을 반복해서 늘리지 않았어요 "
                        "(사진/영상/상품 정보를 더 넣으면 장면이 늘어납니다)")
    return scenes


def layout_context(identity, product, clip_paths, cutout_ok=None) -> layout_engine.LayoutContext:
    from ..director import zoomable
    ba = tuple(product.before_after[:2]) if len(getattr(product, "before_after", []) or []) >= 2 else None
    return layout_engine.LayoutContext(
        photos=list(identity.photos), usage_path=identity.usage_reference, clip_paths=list(clip_paths or []),
        cutout_ok=set(cutout_ok or ()), zoomable={ph["path"] for ph in identity.photos if zoomable(identity, ph["path"])},
        features=[f for f in product.features if f], review_quotes=list(getattr(product, "review_quotes", []) or []),
        before_after=ba, comparison=(list(getattr(product, "comparison", []) or []) or None))


def build_storyboard(plan, identity, product, vision=None, clip_paths: list[str] | None = None, style: str = "STANDARD",
                     mode: str = "PRO", cutout_ok=None, post_layout=None, pattern_guide: dict | None = None) -> Storyboard:
    facts = grounding.allowed_facts(product, vision)
    warnings: list[str] = []
    director = SceneDirector(identity, product, facts, clip_paths)
    scenes = [director.from_legacy(sc, i) for i, sc in enumerate(plan.scenes)]
    total = sum(s.duration for s in scenes)
    cls, rng = duration_class(total)
    scenes = fit_scene_count(scenes, rng, warnings)
    for i, s in enumerate(scenes):                     # 장면이 빠졌어도 첫 장면 전환/CTA 전 전환 규칙 유지
        s.transition = "cut" if i == 0 else s.transition
    styles.apply_tempo(scenes, style, floor=12.6 if getattr(product, "compact", False) else 0.0)
    styles.apply_transitions(scenes, style)
    pattern_applied = {}
    if pattern_guide:                                  # REFERENCE 패턴: 템포/Hook 길이/전환을 패턴에 맞춘다 (구조만, 내용 복사 없음)
        from ..reference_engine.apply import shape_scenes
        pattern_applied = shape_scenes(scenes, pattern_guide)
    layout_engine.select_layouts(scenes, layout_context(identity, product, clip_paths, cutout_ok))
    production = post_layout(scenes) if post_layout else {}      # 출연 방식(REAL_UGC/AI) 계획: 레이아웃 뒤, 모션 선택 앞
    for s in scenes:      # 영상 소스는 시연/사용 장면 레이아웃에서만 재생할 수 있다. 다른 레이아웃이 뽑히면 사진으로 되돌린다 (이미지로 못 여는 파일을 렌더러에 넘기지 않음)
        vs = s.visual_source
        if vs.get("kind") == "user_video" and s.layout not in ("demo", "lifestyle"):
            vs.update({"kind": "user_photo", "path": vs.get("fallback_path") or next((ph["path"] for ph in identity.photos), None),
                       "reason": vs.get("reason", "") + " (이 레이아웃은 영상을 재생하지 않아 사진 사용)"})
    bias = dict(styles.profile(style)["motion"]["bias"])
    for k, w in (((pattern_guide or {}).get("motion") or {}).get("bias") or {}).items():
        bias[k] = bias.get(k, 0.0) + w                    # 참고 패턴의 카메라/모션 선호를 스타일 선호에 더한다
    motion_director.select_motions(scenes, [f for f in product.features if f], bias)
    issues = validator.validate(scenes, [f for f in product.features if f])      # 품질 규칙 검사 + 안전한 자동 수정
    sfx_director.direct_sfx(scenes, **{"ratio": ((pattern_guide or {}).get("sfx") or {}).get("ratio") or styles.profile(style)["sfx"]["ratio"], "heavy": styles.profile(style)["sfx"]["heavy"]})       # 효과음은 layout/motion 이 정해진 뒤 (콜아웃 click, pan swipe 등)
    distinct = {s.visual_source.get("path") for s in scenes if s.visual_source.get("path")}
    if len(scenes) > 2 * len(distinct) + 1:
        warnings.append(f"서로 다른 원본 {len(distinct)}개로 장면 {len(scenes)}개를 만들면 같은 화면이 반복돼요")
    for s in scenes:
        if s.reliability == "C":
            warnings.append(f"{s.scene_id}: 입력에 없는 데이터성 표현({', '.join(c['text'] for c in s.claims if c['reliability'] == 'C')}) - 확인 필요")
        gap = s.visual_source.get("gap")
        if gap:
            warnings.append(f"{s.scene_id}({s.scene_type}): 사용 장면 소스 없음 - 사진 모션으로 대체 (영상/사용 사진을 넣으면 좋아져요)")
    sb = Storyboard(scenes=scenes, mode=mode, style=style, total_duration=round(sum(s.duration for s in scenes), 2),
                    duration_class=cls, scene_range=rng,
                    music={"mood": MUSIC_BY_STYLE.get(style, MUSIC_BY_STYLE["STANDARD"]), "profile": styles.profile(style)["music"],
                           "cues": [{"scene_id": s.scene_id, "cue": s.music_cue} for s in scenes]},
                    facts=[{"text": f, "reliability": "A"} for f in facts], warnings=warnings, issues=issues, production=production or {})
    if pattern_guide:
        from ..reference_engine.apply import report
        sb.production = {**(sb.production or {}), "caption_zone": (pattern_guide.get("caption") or {}).get("zone")}
        sb.production["reference"] = {"applied": pattern_applied, "sources": pattern_guide.get("sources"), "aspects": pattern_guide.get("aspects"),
                                      "style_suggestion": pattern_guide.get("style_suggestion"), "warnings": pattern_guide.get("warnings"), **report(sb, pattern_guide)}
    return sb
