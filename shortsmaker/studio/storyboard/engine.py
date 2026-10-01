"""STORYBOARD ENGINE - 대본(CreativePlan)을 영상 길이에 맞는 Storyboard(JSON)로 바꾼다.

상품 분석 → 판매각 → Hook → Script → [Storyboard] → Scene Director → Preview → Render
기존 director/editor/renderer 는 그대로 두고, 그 사이에 끼워 넣는다.
"""
from __future__ import annotations

from .. import grounding
from . import sfx_director
from .scene_director import SceneDirector
from .schema import Storyboard, duration_class

# 장면 수를 줄여야 할 때 먼저 버리는 순서 (HOOK/PRODUCT_REVEAL/CTA 와 첫 DEMO/BENEFIT 은 보존)
DROP_ORDER = ("PROOF", "FEATURE", "PROBLEM", "DEMO", "BENEFIT")
KEEP_FIRST = {"HOOK", "PRODUCT_REVEAL", "CTA"}
MUSIC_BY_STYLE = {"STANDARD": "clean, upbeat, instrumental, ~100 BPM, 첫 박부터 시작",
                  "FAST_COMMERCE": "energetic, tight drums, ~120 BPM", "PREMIUM": "soft, warm, slow build, ~80 BPM",
                  "UGC_REVIEW": "light acoustic, natural, low volume"}


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


def build_storyboard(plan, identity, product, vision=None, clip_paths: list[str] | None = None, style: str = "STANDARD",
                     mode: str = "PRO") -> Storyboard:
    facts = grounding.allowed_facts(product, vision)
    warnings: list[str] = []
    director = SceneDirector(identity, product, facts, clip_paths)
    scenes = [director.from_legacy(sc, i) for i, sc in enumerate(plan.scenes)]
    total = sum(s.duration for s in scenes)
    cls, rng = duration_class(total)
    scenes = fit_scene_count(scenes, rng, warnings)
    for i, s in enumerate(scenes):                     # 장면이 빠졌어도 첫 장면 전환/CTA 전 전환 규칙 유지
        s.transition = "cut" if i == 0 else s.transition
    sfx_director.direct_sfx(scenes)
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
                    music={"mood": MUSIC_BY_STYLE.get(style, MUSIC_BY_STYLE["STANDARD"]),
                           "cues": [{"scene_id": s.scene_id, "cue": s.music_cue} for s in scenes]},
                    facts=[{"text": f, "reliability": "A"} for f in facts], warnings=warnings)
    return sb
