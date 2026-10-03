"""SNS 마감(Retention Polish): OpusClip 류 자동 편집의 '시청 유지 리듬'을 편집안(EDL)에 더한다. 선택 기능, 기본 OFF.

하는 일 (내용/길이/대사/사진은 바꾸지 않는다 — 이미 만들어진 컷 안에서 '움직임'만 더한다)
1. Retention Rhythm: 한 컷 안에서 시각 변화 없이 오래 이어지는 구간이 있으면, 일정 간격으로 짧은 펀치 줌(패턴 인터럽트)을 넣는다.
   강조 단어 시점/컷 경계/컷 끝과 겹치지 않게 하고, 컷당 2회까지만 쓴다. 스타일별로 간격이 다르다 (FAST 촘촘, STORY 느슨).
2. 진행 막대: 상단 안전영역 아래에 얇은 진행 막대 (이탈 방지 장치, 플랫폼 UI 와 겹치지 않는 위치).
3. 실측 리포트: 가장 긴 '변화 없는 구간', 첫 시각 변화/첫 자막 시각, 자막 읽기 속도(글자/초), 적용 전/후 비교.
   점수를 꾸미지 않고 측정값과 기준(경고/통과)만 낸다.
"""
from __future__ import annotations

# 스타일별 펀치 간격(초)과 한계(초): 변화 없는 구간이 limit 을 넘으면 간격마다 펀치를 넣는다
RHYTHM = {"FAST_COMMERCE": {"interval": 1.6, "limit": 2.4}, "STORY_AD": {"interval": 2.6, "limit": 3.4},
          "UGC_REVIEW": {"interval": 2.0, "limit": 2.9}, "STANDARD": {"interval": 2.2, "limit": 3.0}}
MAX_PER_SHOT = 2
EDGE = 0.45            # 컷 시작/끝과 이 시간 안에는 펀치를 넣지 않는다
APART = 0.8            # 기존 펀치/강조 시점과 최소 간격
CPS_WARN = 12.0        # 한글 자막 읽기 속도 경고 기준 (글자/초)


def _events(shots: list) -> list[float]:
    """타임라인 상 '시각 변화' 시점: 컷 경계 + 펀치 + 강조 시점."""
    ev, t = [0.0], 0.0
    for s in shots:
        t0 = t
        ev.append(round(t0, 3))
        for pt in s.punch_at:
            ev.append(round(t0 + pt, 3))
        if s.emph_at is not None:
            ev.append(round(t0 + s.emph_at, 3))
        t += s.duration
    ev.append(round(t, 3))
    return sorted(set(ev))


def longest_static(shots: list) -> float:
    ev = _events(shots)
    return round(max((b - a) for a, b in zip(ev, ev[1:])), 2) if len(ev) > 1 else 0.0


def _cps(shots: list) -> float:
    worst = 0.0
    for s in shots:
        if not s.caption_words:
            continue
        chars = sum(len(w.text) for w in s.caption_words)
        span = max(0.5, s.duration - s.caption_words[0].start)
        worst = max(worst, chars / span)
    return round(worst, 1)


def apply(edl: dict, style: str) -> dict:
    """edl["shots"] 에 펀치/진행 막대를 직접 반영하고 리포트를 돌려준다. 컷 수/길이/대사는 불변."""
    shots = edl["shots"]
    cfg = RHYTHM.get(style, RHYTHM["STANDARD"])
    before = longest_static(shots)
    total = sum(s.duration for s in shots) or 1.0
    added = 0
    t0 = 0.0
    for s in shots:
        marks = list(s.punch_at) + ([s.emph_at] if s.emph_at is not None else [])
        n = 0
        t = cfg["interval"]
        while t < s.duration - EDGE and n < MAX_PER_SHOT and s.duration > cfg["limit"] * 0.75:
            if t >= EDGE and all(abs(t - m) >= APART for m in marks):
                s.punch_at.append(round(t, 2))
                marks.append(t)
                n += 1
                added += 1
            t += cfg["interval"]
        s.data = {**(s.data or {}), "progress": (round(t0 / total, 4), round((t0 + s.duration) / total, 4))}
        t0 += s.duration
    after = longest_static(shots)
    timing = edl.get("timing") or {}
    cps = _cps(shots)
    findings = []
    findings.append({"check": "longest_static_seconds", "value": after, "limit": cfg["limit"], "status": "PASS" if after <= cfg["limit"] else "WARN",
                     "note": f"변화 없는 구간 최장 {after}s (적용 전 {before}s)"})
    fvc, fc = timing.get("first_visual_change"), timing.get("first_caption")
    findings.append({"check": "first_visual_change", "value": fvc, "limit": 1.2, "status": "PASS" if fvc is not None and fvc <= 1.2 else "WARN"})
    findings.append({"check": "first_caption", "value": fc, "limit": 1.0, "status": "PASS" if fc is not None and fc <= 1.0 else "WARN"})
    findings.append({"check": "caption_chars_per_second", "value": cps, "limit": CPS_WARN, "status": "PASS" if cps <= CPS_WARN else "WARN",
                     "note": "자막이 너무 빠르면 읽기 어려워요" if cps > CPS_WARN else ""})
    return {"enabled": True, "style": style, "interval": cfg["interval"], "punches_added": added, "longest_static_before": before, "longest_static_after": after,
            "progress_bar": True, "shots": len(shots), "total": round(total, 2), "findings": findings,
            "warnings": [f"{f['check']}: {f.get('note') or f['value']}" for f in findings if f["status"] == "WARN"]}
