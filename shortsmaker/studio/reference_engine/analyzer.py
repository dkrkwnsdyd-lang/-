"""VIDEO REFERENCE ANALYZER: 참고 영상 → 추상 패턴 후보(raw). 원본 영상 다운로드/재사용은 하지 않는다.

입력 방법
- youtube_url : 공개 YouTube 영상 URL → Gemini 영상 이해 (영상은 Google 이 보고, 우리는 구조 JSON 만 받는다)
- upload      : 사용자가 올린 영상 파일 → 로컬 측정(컷/템포/밝기 급변) + 대표 프레임 Vision 분석 (프레임은 분석 후 삭제)
- notes       : 사용자가 영상 구조를 글로 적은 메모 → 텍스트 분석
- Instagram/Xiaohongshu URL 은 영상을 가져올 수 없으므로(다운로드 기능 제외) UNVERIFIED + 올바른 입력 방법을 안내한다.
말/자막 원문은 해시(fingerprint)로만 남기고 버린다.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from ...video import ffmpeg_exe
from ..reference import analyze_local
from ..reference import youtube_video_id as _yt
from . import vocab
from .platforms import detect_platform, usable_url

SCHEMA = (
    '{"hook_pattern":"%s","hook_duration":0.0,"video_duration":0.0,"scene_count":0,"story_stages":["%s"],"stage_times":[{"stage":"","start":0.0}],'
    '"product_reveal_time":0.0,"caption_density":"low|medium|high","caption_position":"top|center|bottom","caption_pattern":"%s",'
    '"caption_change_frequency":"slow|medium|fast","camera_motion":["%s"],"image_motion":["%s"],"transition_pattern":["%s"],"sfx_pattern":"none|sparse|frequent",'
    '"bgm_mood":"%s","cta_pattern":"%s","cta_position":0.0,"content_style":"%s","emotion_curve":"%s","selling_structure":"short Korean label",'
    '"story_roles":{"situation":"","problem":"","emotion":"","turning_point":"","product_role":"","result":"","cta":""},'
    '"scores":{"hook_strength":0,"story_strength":0,"editing_quality":0,"visual_quality":0,"shortform_fit":0,"sales_connection":0},'
    '"language":"ko|zh|en|other","_transcript":"spoken words (will be discarded)","_captions":"on-screen text (will be discarded)"}') % (
        "|".join(vocab.HOOK_PATTERNS), "|".join(vocab.STORY_STAGES), "|".join(vocab.CAPTION_PATTERNS), "|".join(vocab.MOTION_PATTERNS),
        "|".join(vocab.MOTION_PATTERNS), "|".join(vocab.TRANSITION_PATTERNS), "|".join(vocab.BGM_MOODS), "|".join(vocab.CTA_PATTERNS),
        "|".join(vocab.CONTENT_STYLES), "|".join(vocab.EMOTION_CURVES))


def system_prompt(platform: str) -> str:
    return ("You analyze the PRODUCTION STRUCTURE of a short-form shopping/product video so that a different video can be built from the same editing formula. "
            "Describe structure only. Never output the creator's sentences as patterns; story_roles and labels are ABSTRACT Korean descriptions (max 30 chars) "
            "of the situation/emotion type, not quotes or translations. Do not report prices, discounts, sales numbers, ratings, reviews, or product claims. "
            f"Platform focus: {vocab.PLATFORM_FOCUS.get(platform, vocab.PLATFORM_FOCUS['other'])}. "
            "Use ONLY the allowed vocabulary values. Be honest: if you cannot tell, use null. Times are seconds from the start. "
            "Scores are 0-100 and strict; judge craft, not popularity or view counts. "
            "Answer JSON only with this shape: " + SCHEMA)


# ------------------------------------------------------------------ 로컬 측정 (업로드 영상)
def local_metrics(path: str) -> dict:
    """컷 감지 기반 템포. 영상 파일을 읽을 수 없으면 {}."""
    try:
        a = analyze_local(path)
    except Exception:
        return {}
    dur = float(a.get("duration") or 0.0)
    cuts = a.get("pattern_interrupts") or 0
    avg = a.get("average_cut_length")
    return {"duration": round(dur, 2), "cuts": int(cuts), "scene_count": int(cuts) + 1 if dur else None, "avg_scene": avg,
            "first_visual_change": a.get("first_visual_change_time"), "camera_motion": a.get("camera_motion")}


def cut_times(path: str, thr_floor: float = 18.0) -> list[float]:
    from ..qa import sample_frames
    try:
        frames = sample_frames(Path(path), fps=10, size=(90, 160))
    except Exception:
        return []
    if len(frames) < 3:
        return []
    diffs = np.array([np.abs(a - b).mean() for a, b in zip(frames, frames[1:])])
    thr = max(thr_floor, float(np.median(diffs) * 4))
    return [round((i + 1) / 10, 2) for i, d in enumerate(diffs) if d > thr]


def sample_jpgs(path: str, duration: float, out_dir: Path, n: int = 8) -> list[tuple[float, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for k in range(n):
        t = max(0.0, duration * (k + 0.5) / n)
        dst = out_dir / f"ref_{k}.jpg"
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale='min(512,iw)':-2",
                        "-q:v", "4", str(dst)], capture_output=True)
        if dst.exists():
            res.append((round(t, 2), str(dst)))
    return res


# ------------------------------------------------------------------ 분석 진입점
def analyze(router, *, url: str = "", file: str = "", notes: str = "", platform: str = "") -> dict:
    """반환: {platform, source_ref, method, status, data(raw JSON), local, note}. 예외를 밖으로 던지지 않는다."""
    platform = platform or detect_platform(file or url)
    out = {"platform": platform, "source_ref": (Path(file).name if file else url), "method": "none", "status": "UNVERIFIED", "data": {}, "local": {}, "note": ""}
    try:
        if file and Path(file).exists():
            return _from_upload(router, file, platform, out)
        if url:
            ok, why = usable_url(url)
            if not ok:
                out["note"] = why
                return out
            if _yt(url):
                return _from_youtube(router, url, platform, out)
            if notes.strip():
                return _from_notes(router, notes, platform, out, with_url_note=True)
            out["note"] = (f"{vocab.PLATFORM_KO.get(platform, '이 플랫폼')} 링크는 영상을 직접 가져올 수 없어 분석할 수 없어요(영상 다운로드 기능은 제외). "
                           "영상 파일을 올리거나, 영상 구조를 글로 적어 주세요.")
            return out
        if notes.strip():
            return _from_notes(router, notes, platform, out)
    except Exception as e:                                        # 분석 실패가 서버 오류가 되지 않게
        out["note"] = f"분석 중 오류: {type(e).__name__}: {str(e)[:120]}"
    if not out["note"]:
        out["note"] = "분석할 URL/영상/메모가 없어요"
    return out


def _from_youtube(router, url, platform, out):
    if router is None or not router.has_real("vision"):
        out["note"] = "영상 이해 provider(Gemini)가 연결되지 않아 YouTube 영상을 분석할 수 없어요"
        return out
    res = router.run("vision", "json", need=["youtube_url"], system=system_prompt(platform), user="Analyze this video's production structure.",
                     video_url=url, temperature=0)
    data = res.value if isinstance(res.value, dict) else {}
    out.update({"method": f"{res.provider}:{res.model}:youtube_url", "data": data, "status": "VERIFIED" if data else "UNVERIFIED"})
    if not data:
        out["note"] = "영상 구조 응답을 받지 못했어요"
    return out


def _from_upload(router, path, platform, out):
    lm = local_metrics(path)
    out["local"] = lm
    out["method"] = "local_cut_detection"
    if not lm:
        out["note"] = "영상 파일을 읽을 수 없어요"
        return out
    cuts = cut_times(path)
    out["local"]["cut_times"] = cuts
    out["status"] = "PARTIAL"
    if router is not None and router.has_real("vision"):
        with tempfile.TemporaryDirectory() as td:
            frames = sample_jpgs(path, lm["duration"], Path(td))
            if frames:
                stamp = ", ".join(f"image {i + 1}={t}s" for i, (t, _) in enumerate(frames))
                measured = f"Measured: duration {lm['duration']}s, cuts at {cuts[:40]}, average scene {lm.get('avg_scene')}s."
                res = router.run("vision", "json", system=system_prompt(platform), user=f"Frames in order: {stamp}. {measured} Infer the structure; use the measured values for tempo.",
                                 images=[p for _, p in frames], temperature=0)
                data = res.value if isinstance(res.value, dict) else {}
                if data:
                    out.update({"method": f"{res.provider}:{res.model}:frames+local", "data": data, "status": "VERIFIED"})
    if out["status"] != "VERIFIED":
        out["note"] = "Vision 분석을 쓸 수 없어 컷/템포만 측정했어요 (후크/스토리/자막 패턴은 비어 있음)"
    return out


def _from_notes(router, notes, platform, out, with_url_note=False):
    if router is None or not router.has_real("llm"):
        out["note"] = "LLM 이 연결되지 않아 메모를 분석할 수 없어요"
        return out
    res = router.run("llm", "json", system=system_prompt(platform), user="Here are the user's notes describing a video's structure (may be in any language):\n" + notes[:3000],
                     temperature=0)
    data = res.value if isinstance(res.value, dict) else {}
    out.update({"method": f"{res.provider}:{res.model}:notes", "data": data, "status": "PARTIAL" if data else "UNVERIFIED"})
    out["note"] = "사용자가 적은 메모 기반 분석이라 정확도가 낮을 수 있어요" if data else "메모에서 구조를 읽지 못했어요"
    return out
