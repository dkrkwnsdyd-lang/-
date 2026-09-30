"""AI EDITOR - 편집 판단 (렌더러는 판단하지 않는다).

- 첫 3초 규칙 (0.0 움직임, 0.3~0.7 첫 자막, 0.8~1.3 첫 화면 변화, 2~4초 제품 공개)
- 긴 장면은 다른 구도로 나눠 같은 구도 반복/지루함 제거
- 컷 길이를 음악 박자(반박자)에 맞춤 (music_hit)
- 의미 변화(자막 강조)와 화면 변화(펀치 줌) 동기화
- 효과음/자막 타이밍 결정
"""
from __future__ import annotations

from dataclasses import asdict

from .. import brain
from .audio import BEAT
from .director import BEAT_DURATION, CreativePlan, Scene
from .motion import CaptionWord, Shot, split_caption

HALF_BEAT = BEAT / 2
SPLIT_ALT = {"hero_push": "macro", "parallax": "macro", "light_sweep": "macro", "macro": "detail_pan",
             "detail_pan": "macro", "punch_in": "macro", "whip_reveal": "macro", "rack_focus": "macro",
             "problem_card": "problem_card", "cta_card": "cta_card"}


def quantize(d: float, minimum: float = 0.9) -> float:
    return max(minimum, round(d / HALF_BEAT) * HALF_BEAT)


def time_words(caption: str, start: float, span: float, voice_span: float | None = None) -> list[CaptionWord]:
    rules = brain.system("caption_rules")
    words = split_caption(caption, rules["max_chars_per_line"], rules["max_lines"])
    if not words:
        return []
    span = voice_span or span
    weights = [max(1, len(w.text)) for w in words]
    total = sum(weights)
    t = start
    for w, wt in zip(words, weights):
        w.start = round(t, 3)
        t += span * wt / total
    return words


SAFE_SPLIT_ALT = {"hero_push": "parallax", "parallax": "light_sweep", "light_sweep": "hero_push",
                  "punch_in": "hero_push", "whip_reveal": "hero_push", "rack_focus": "hero_push",
                  "problem_card": "problem_card", "cta_card": "cta_card"}


def edit(plan: CreativePlan, takes: dict[str, dict], voice: dict[str, tuple[float, str]] | None = None,
         label: str = "", cta_text: str | None = None, zoomable_paths: set[str] | None = None) -> dict:
    """plan + 선택된 take 파라미터 -> EDL (shots, sfx events, timing)."""
    rules = brain.system("quality_rules")
    pacing = rules["pacing"]
    f3 = rules["first_3_seconds"]
    voice = voice or {}
    shots: list[Shot] = []
    events: list[dict] = []
    voice_cues: list[tuple[float, str]] = []
    timeline = 0.0
    reveal_at = None
    decisions: list[str] = []

    for si, scene in enumerate(plan.scenes):
        take = takes.get(scene.scene_id, {})
        shot_type = take.get("shot", scene.shot)
        source = take.get("source", scene.reference_image)
        lo, hi = BEAT_DURATION[scene.beat]
        dur = scene.duration
        vo, vo_path = voice.get(scene.scene_id, (None, ""))
        if vo:  # Dead air 제거: 대사 길이에 맞춤
            dur = max(lo * 0.8, vo + 0.25)
        dur = quantize(dur)
        caption = scene.caption
        if scene.beat == "cta" and cta_text:
            caption = cta_text

        # 긴 장면은 두 컷으로 (같은 구도 반복 방지)
        split = dur > pacing["max_shot_length"] or (plan.mode == "PRO" and not plan.compact and dur >= 2.7
                                                       and scene.beat in ("demo", "detail", "benefit"))
        if scene.beat == "hook" and dur > 1.5:
            split = True  # 첫 화면 변화 0.8~1.3초
        parts = [dur]
        if split:
            first = quantize(1.2 if scene.beat == "hook" else dur / 2, 0.6)
            first = min(first, dur - 0.6)
            parts = [first, round(dur - first, 3)]
            decisions.append(f"{scene.scene_id}: {dur:.1f}s 장면을 {parts} 두 컷으로 분할")

        cap_start = f3["first_caption"][0] + 0.05 if si == 0 else 0.08
        span = min(dur * 0.55, 1.8)
        words = time_words(caption, cap_start, span, vo * 0.9 if vo else None)
        if vo:
            voice_cues.append((timeline + 0.05, vo_path))

        offset = 0.0
        for pi, pdur in enumerate(parts):
            st = shot_type
            if pi > 0:
                st = SPLIT_ALT.get(shot_type, "macro")
                if zoomable_paths is not None and st in ("macro", "detail_pan") and source not in zoomable_paths:
                    st = SAFE_SPLIT_ALT.get(shot_type, "hero_push")
            local_words = [CaptionWord(w.text, round(w.start - offset, 3) if w.start - offset > 0 else -1.0,
                                       w.emphasis, w.line) for w in words]
            punch = []
            if scene.beat == "hook" and pi == 0:
                punch = []
            elif pi == 0 and any(w.emphasis for w in words) and scene.beat in ("reveal", "demo", "benefit"):
                # 강조 단어 등장 순간에 펀치 줌 (의미 변화 = 화면 변화)
                em = next(w for w in words if w.emphasis)
                if 0.2 < em.start < pdur - 0.3:
                    punch = [em.start]
            transition = scene.transition if pi == 0 else "cut"
            if si == 0 and pi == 0:
                transition = "cut"
            shots.append(Shot(
                scene_id=scene.scene_id, shot=st, source=source if st != "macro" or pi == 0 else
                (take.get("detail_source") or source), duration=round(pdur, 3), caption_words=local_words,
                transition_in=transition, punch_at=punch, zoom=tuple(take.get("zoom", (1.0, 1.08))),
                pan=tuple(take.get("pan", (1.0 if si % 2 == 0 else -1.0, 0.0))), focus=take.get("focus"),
                grade="problem" if scene.beat == "problem" else "normal", label=label))
            abs_t = timeline + offset
            if transition == "whip":
                events.append({"t": max(0, abs_t - 0.08), "sfx": "whoosh", "gain": 0.55})
            for pt in punch:
                events.append({"t": abs_t + pt, "sfx": "hit", "gain": 0.5})
            offset += pdur
        for w in words:
            if w.emphasis:
                events.append({"t": timeline + w.start, "sfx": "pop", "gain": 0.45})
        if scene.beat == "reveal" and reveal_at is None:
            reveal_at = timeline
            events.append({"t": max(0, timeline - 0.7), "sfx": "riser", "gain": 0.45})
            events.append({"t": timeline, "sfx": "hit", "gain": 0.6})
        timeline += dur

    cuts = []
    t = 0.0
    for s in shots:
        cuts.append(round(t, 3))
        t += s.duration
    lengths = [s.duration for s in shots]
    first_caption = next((round(w.start, 3) for w in shots[0].caption_words if w.start >= 0), None) if shots else None
    return {
        "shots": shots,
        "events": events,
        "voice": [(t0, p) for t0, p in voice_cues if p],
        "total": round(t, 3),
        "timing": {
            "cuts": cuts,
            "first_visual_change": cuts[1] if len(cuts) > 1 else None,
            "first_caption": first_caption,
            "reveal_at": round(reveal_at, 3) if reveal_at is not None else None,
            "avg_shot": round(sum(lengths) / len(lengths), 3) if lengths else 0,
            "max_shot": max(lengths) if lengths else 0,
            "min_shot": min(lengths) if lengths else 0,
        },
        "decisions": decisions,
    }


def edl_summary(edl: dict) -> dict:
    return {"total": edl["total"], "timing": edl["timing"], "decisions": edl["decisions"],
            "shots": [{k: v for k, v in asdict(s).items() if k != "caption_words"} |
                      {"caption": " ".join(w.text for w in s.caption_words)} for s in edl["shots"]]}
