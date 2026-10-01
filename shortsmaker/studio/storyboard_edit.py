"""STORYBOARD -> EDL (Renderer 쪽 입력 변환).

AI 는 Storyboard(JSON) 만 만들고, 여기서 시간/자막 타이밍/효과음 이벤트가 붙은 편집안(EDL)으로 바꾼다.
Renderer(MotionRenderer) 는 이 EDL 의 Shot 만 읽어 MP4 를 만든다. 기존 editor.edit 는 그대로 두고(레거시 경로), 이 경로는 별도.
- 장면 1개 = 컷 1개 (같은 사진을 확대만 바꿔 쪼개서 컷 수를 채우지 않는다)
- 효과음은 Storyboard 가 정한 전환/강조 지점에만
"""
from __future__ import annotations

from .. import brain
from .director import BEAT_DURATION
from .editor import quantize, time_words
from .motion import Shot
from .storyboard.schema import Storyboard
from .storyboard.scene_director import caption_text

HOOK_STRONG = {"punch_in", "mask_reveal", "shake", "zoom_in", "object_focus"}   # 첫 1초 안에 화면이 확 바뀌는 모션
LEAD_SFX = {"whoosh": -0.06, "swipe": -0.04, "riser": -0.5}                       # 전환음은 컷 직전에 시작


def edit_from_storyboard(sb: Storyboard, voice: dict | None = None, label: str = "", cta_text: str | None = None) -> dict:
    f3 = brain.system("quality_rules")["first_3_seconds"]
    voice = voice or {}
    shots: list[Shot] = []
    events: list[dict] = []
    voice_cues: list[tuple[float, str]] = []
    timeline = 0.0
    reveal_at = None
    decisions: list[str] = []
    for si, ss in enumerate(sb.scenes):
        vo, vo_path = voice.get(ss.scene_id, (None, ""))
        lo = BEAT_DURATION.get(ss.legacy_beat or "hook", (1.5, 2.5))[0]
        dur = max(lo * 0.8, vo + 0.25) if vo else ss.duration            # Dead air 제거: 대사 길이에 맞춤
        dur = quantize(dur)
        caption = cta_text if (ss.scene_type == "CTA" and cta_text) else caption_text(ss)
        cap_start = f3["first_caption"][0] + 0.05 if si == 0 else 0.08
        words = time_words(caption, cap_start, min(dur * 0.55, 1.8), vo * 0.9 if vo else None)
        emph_at = next((w.start for w in words if w.emphasis), None)
        src = ss.visual_source.get("path") or ""
        shots.append(Shot(
            scene_id=ss.scene_id, shot="hero_push", source=src, duration=round(dur, 3), caption_words=words,
            transition_in="cut" if si == 0 else ss.transition, layout=ss.layout, motion=ss.image_motion,
            source2=ss.secondary_source, data=dict(ss.layout_data), emph_at=emph_at, label=label))
        if vo:
            voice_cues.append((timeline + 0.05, vo_path))
        for ev in ss.sound_effect:
            if ev["at"] == "emphasis":
                t = timeline + (emph_at if emph_at is not None else min(0.4, dur * 0.3))
            elif ev["at"] == "end":
                t = timeline + dur - 0.2
            else:
                t = timeline + LEAD_SFX.get(ev["sfx"], 0.0)
            events.append({"t": max(0.0, round(t, 3)), "sfx": ev["sfx"], "gain": ev.get("gain", 0.5)})
        if ss.scene_type == "PRODUCT_REVEAL" and reveal_at is None:
            reveal_at = timeline
        decisions.append(f"{ss.scene_id} {ss.scene_type}: layout={ss.layout} motion={ss.image_motion} {dur:.1f}s")
        timeline += dur
    cuts, t = [], 0.0
    for s in shots:
        cuts.append(round(t, 3))
        t += s.duration
    lengths = [s.duration for s in shots]
    fvc = cuts[1] if len(cuts) > 1 else None
    if sb.scenes and sb.scenes[0].image_motion in HOOK_STRONG:            # 첫 장면 모션이 1초 안에 화면을 바꾼다 (Hook 첫 2초 시각 변화)
        fvc = min(fvc, 0.9) if fvc is not None else 0.9
    first_caption = next((round(w.start, 3) for w in shots[0].caption_words if w.start >= 0), None) if shots else None
    return {
        "shots": shots, "events": events, "voice": [(t0, p) for t0, p in voice_cues if p], "total": round(t, 3), "storyboard": True,
        "timing": {"cuts": cuts, "first_visual_change": fvc, "first_caption": first_caption,
                   "reveal_at": round(reveal_at, 3) if reveal_at is not None else None,
                   "avg_shot": round(sum(lengths) / len(lengths), 3) if lengths else 0,
                   "max_shot": max(lengths) if lengths else 0, "min_shot": min(lengths) if lengths else 0},
        "decisions": decisions,
    }
