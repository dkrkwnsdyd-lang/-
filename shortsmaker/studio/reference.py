"""REFERENCE MINER - 참고 영상의 '구조'만 분석한다 (문장/화면 복제 금지).

- 로컬 mp4 파일: 컷 감지로 컷 길이/첫 화면 변화/움직임 측정 -> PARTIAL
- 공개 YouTube URL: 영상 이해 API(Gemini) 연결 시 구조 분석 -> VERIFIED/PARTIAL
- 둘 다 불가: URL 만 기록 -> UNVERIFIED (SHORTS BRAIN 학습 금지)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .. import brain
from ..sources import youtube_video_id
from .qa import audio_level, probe_video, sample_frames

FIELDS = ["hook_type", "hook_structure", "first_visual_change_time", "product_reveal_time", "average_cut_length",
          "camera_type", "camera_angle", "camera_motion", "story_pattern", "caption_style", "caption_density",
          "voice_speed", "pattern_interrupts", "selling_angle", "CTA_type", "CTA_timing", "music_style", "visual_style"]


def analyze_local(path: str | Path) -> dict:
    path = Path(path)
    info = probe_video(path)
    frames = sample_frames(path, fps=10, size=(90, 160))
    diffs = np.array([np.abs(a - b).mean() for a, b in zip(frames, frames[1:])]) if len(frames) > 1 else np.array([])
    cuts = []
    if len(diffs):
        thr = max(18.0, float(np.median(diffs) * 4))
        cuts = [round((i + 1) / 10, 2) for i, d in enumerate(diffs) if d > thr]
    bounds = [0.0] + cuts + [info["duration"]]
    lengths = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]
    out = {k: None for k in FIELDS}
    out.update({
        "first_visual_change_time": cuts[0] if cuts else None,
        "average_cut_length": round(float(np.mean(lengths)), 2) if lengths else None,
        "camera_motion": "static" if len(diffs) and float(np.median(diffs)) < 1.0 else "moving",
        "pattern_interrupts": len(cuts),
        "duration": info["duration"],
        "audio_mean_db": audio_level(path) if info["has_audio"] else None,
    })
    return out


# 검색결과/탐색/태그 페이지는 '영상 하나'가 아니므로 참고 영상으로 분석하지 않는다.
SEARCH_PATTERNS = [
    r"xiaohongshu\.com/(search_result|explore\?|web_search)", r"rednote\.com/(search|explore\?)",
    r"youtube\.com/results", r"youtube\.com/(hashtag|@[^/]+/?$|channel/[^/]+/?$|playlist)",
    r"tiktok\.com/(search|tag|discover)", r"instagram\.com/(explore|reels/?$)", r"threads\.(net|com)/search",
    r"[?&](search_query|keyword|q|query)=",
]


def classify_reference_url(ref: str) -> str:
    """LOCAL_FILE | INDIVIDUAL_VIDEO | SEARCH_RESULT | UNKNOWN_URL"""
    import re
    if not ref:
        return "UNKNOWN_URL"
    if Path(ref).exists():
        return "LOCAL_FILE"
    if youtube_video_id(ref):
        return "INDIVIDUAL_VIDEO"
    if any(re.search(pat, ref, re.I) for pat in SEARCH_PATTERNS):
        return "SEARCH_RESULT"
    return "UNKNOWN_URL"


def analyze_reference(ref: str, router=None) -> dict:
    """결과: {"source", "status", "analysis", "kind"}"""
    kind = classify_reference_url(ref)
    if kind == "SEARCH_RESULT":
        return {"source": ref, "status": "UNVERIFIED", "analysis": {}, "method": "none", "kind": kind,
                "note": "개별 영상 링크가 필요합니다 (검색결과/탐색 페이지는 영상 하나로 분석하지 않아요). 학습에 반영하지 않음"}
    if ref and Path(ref).exists():
        return {"source": ref, "status": "PARTIAL", "analysis": analyze_local(ref),
                "method": "local_cut_detection"}
    if ref and youtube_video_id(ref) and router is not None and router.has_real("vision"):
        system = ("Analyze the STRUCTURE of this short-form shopping video. Never copy sentences. "
                  "Convert the hook into an abstract formula with [slots], e.g. '아직도 [불편한 행동] 하세요?'. "
                  "Return JSON with keys: " + ", ".join(FIELDS) + ", hook_formula. Use null when unsure.")
        try:
            res = router.run("vision", "json", need=["youtube_url"], system=system,
                             user="Analyze the video structure.", video_url=ref)
            data = res.value if isinstance(res.value, dict) else {}
            data.pop("transcript", None)
            filled = sum(1 for k in FIELDS if data.get(k) not in (None, "", []))
            status = "VERIFIED" if filled >= len(FIELDS) * 0.8 else "PARTIAL"
            return {"source": ref, "status": status, "analysis": data, "method": f"{res.provider}:{res.model}"}
        except Exception as e:
            return {"source": ref, "status": "UNVERIFIED", "analysis": {}, "method": "failed", "error": str(e)[:200]}
    return {"source": ref, "status": "UNVERIFIED", "analysis": {}, "method": "none", "kind": kind,
            "note": "영상 분석 provider 미연결 또는 개별 영상 링크가 아님 - 구조를 확인할 수 없어 학습에 반영하지 않음"}


def learn(result: dict, knowledge: brain.LearnedKnowledge) -> bool:
    """VERIFIED/PARTIAL 만 reference_patterns 에 저장 (문장 원문 저장 금지)."""
    a = dict(result.get("analysis") or {})
    for k in ("hook_text", "transcript", "captions_text"):
        a.pop(k, None)
    return knowledge.add("reference_patterns", {"source": result["source"], "status": result["status"],
                                                "structure": a})


def dumps(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
