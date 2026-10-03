"""Reference Analyzer: 레퍼런스 영상 하나 → referenceAnalysis (구조화 JSON).

입력: 업로드 영상(1차 기본: 로컬 측정 + 대표 프레임 Vision), 공개 YouTube URL(Gemini 영상 이해), 구조 메모(글).
Instagram/샤오홍슈/TikTok URL 은 영상 다운로드를 하지 않으므로 분석하지 않고 올바른 입력 방법을 안내한다 (URL 수집은 별도 모듈로 분리된 2차 범위).
한 레퍼런스가 실패해도 예외를 던지지 않고 status=FAILED + 사용자용 메시지를 돌려준다 (다른 레퍼런스는 계속 진행).
무거운 로컬 분석(ffmpeg 프레임/컷 감지)은 이 함수를 호출할 때만 import/실행한다 (Mode OFF 에서는 실행되지 않음).
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import schema

MAX_FILE_MB = 200

SYSTEM = (
    "You analyze the PRODUCTION STRUCTURE of a short-form UGC-style product ad so that a DIFFERENT video can be built with the same directing principles. "
    "Describe structure and technique only; never copy the creator's sentences. All text labels are ABSTRACT Korean descriptions (max 40 chars), not quotes or translations. "
    "Do not report prices, discounts, sales numbers, ratings, reviews or product claims. Use ONLY the allowed vocabulary values; use null when you cannot tell. Times are seconds. "
    "Scores are 0-100, strict, judging craft (not popularity). Answer JSON only with this shape: "
    '{"hook":{"first_1s":"","first_3s":"","first_scene":"","attention_devices":["' + "|".join(schema.ATTENTION) + '"],"problem_raised":false,"curiosity":false,"twist":false,"result_first":false,'
    '"hook_pattern":"' + "|".join(schema.HOOK_PATTERNS) + '"},'
    '"ugc_person":{"face_visible":false,"mode":"' + "|".join(schema.PERSON_MODES) + '","expression":"","gaze":"' + "|".join(schema.GAZE) + '","gestures":[""],"product_grip":"",'
    '"authenticity_cues":["' + "|".join(schema.AUTHENTICITY) + '"]},'
    '"product":{"first_appearance":0.0,"closeup":false,"usage_process":false,"demonstration":false,"before_after":false,"result_screen":false,"usp_emphasis":"' + "|".join(schema.USP_EMPHASIS) + '"},'
    '"camera":{"shot_sizes":["' + "|".join(schema.SHOT_SIZES) + '"],"angles":["' + "|".join(schema.ANGLES) + '"],"movements":["' + "|".join(schema.MOVEMENTS) + '"]},'
    '"editing":{"avg_cut":0.0,"cut_speed":"slow|medium|fast","text_timing":0.0,"caption_position":"top|center|bottom","emphasis_caption":false,"screen_zoom":false,'
    '"sfx":"none|sparse|frequent","bgm_mood":"' + "|".join(schema.BGM) + '"},'
    '"cta":{"style":"' + "|".join(schema.CTA_STYLES) + '","position":0.0},'
    '"structure":[{"stage":"' + "|".join(schema.STAGES) + '","start":0.0,"end":0.0}],"emotional_tone":"","useful_patterns":["short abstract Korean pattern"],'
    '"scores":{"hook_strength":0,"ugc_authenticity":0,"demonstration_clarity":0,"editing_quality":0,"sales_connection":0},"video_duration":0.0,"language":"ko|zh|en|other",'
    '"_transcript":"spoken words (discarded after hashing)","_captions":"on-screen text (discarded after hashing)"}'
)


def _result(kind: str, ref: str, status: str = "FAILED", analysis: dict | None = None, fp: list | None = None, error: str = "", method: str = "") -> dict:
    return {"id": "ur_" + uuid.uuid4().hex[:10], "source_kind": kind, "source_ref": ref, "status": status, "analysis": analysis, "fingerprint": fp or [], "error": error,
            "method": method, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def analyze(router, *, file: str = "", url: str = "", notes: str = "") -> dict:
    """결과: {id, source_kind, source_ref, status VERIFIED|PARTIAL|FAILED, analysis, fingerprint, error(사용자용), method}"""
    try:
        if file:
            return _upload(router, file)
        if url.strip():
            return _url(router, url.strip(), notes)
        if notes.strip():
            return _notes(router, notes, "")
        return _result("none", "", error="영상 파일, YouTube 링크, 또는 영상 구조 메모 중 하나가 필요해요")
    except Exception as e:                                                 # 어떤 오류도 다른 레퍼런스에 영향을 주지 않는다
        return _result("upload" if file else "url", Path(file).name if file else url, error=f"분석 중 오류가 났어요: {type(e).__name__}: {str(e)[:100]}")


def _finish(raw: dict, kind: str, ref: str, method: str, local: dict | None, base_status: str) -> dict:
    from ..reference_engine import fingerprint
    texts = [str(raw.get("_transcript") or ""), str(raw.get("_captions") or "")]
    fp = fingerprint.make(texts) if any(t.strip() for t in texts) else []
    a = schema.normalize(raw, local)
    ratio = schema.filled_ratio(a)
    if ratio < 0.15 and not a["structure"]:
        return _result(kind, ref, error="영상에서 연출 구조를 충분히 읽지 못했어요 (영상이 너무 짧거나 화면이 어두울 수 있어요)", method=method)
    status = base_status if ratio >= 0.5 else "PARTIAL"
    a["coverage"] = round(ratio, 2)
    return _result(kind, ref, status, a, fp, method=method)


def _upload(router, file: str) -> dict:
    p = Path(file)
    if not p.exists():
        return _result("upload", p.name, error="영상 파일을 찾을 수 없어요")
    if p.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        return _result("upload", p.name, error=f"영상이 너무 커요 ({MAX_FILE_MB}MB 이하로 올려 주세요)")
    from ..reference_engine import analyzer as ra                          # 무거운 의존성(numpy/ffmpeg)은 여기서 처음 불러온다
    lm = ra.local_metrics(str(p))
    if not lm:
        return _result("upload", p.name, error="지원하지 않는 영상이거나 파일이 손상됐어요 (mp4/mov 로 다시 올려 주세요)")
    lm["cut_times"] = ra.cut_times(str(p))
    if router is None or not router.has_real("vision"):
        a = schema.normalize({"video_duration": lm["duration"]}, lm)
        a["coverage"] = 0.1
        return _result("upload", p.name, "PARTIAL", a, error="Vision 분석을 쓸 수 없어 컷 길이만 측정했어요 (Hook/UGC 연출 패턴은 비어 있음)", method="local_only")
    with tempfile.TemporaryDirectory() as td:
        frames = ra.sample_jpgs(str(p), lm["duration"], Path(td), 8)
        if not frames:
            return _result("upload", p.name, error="영상에서 프레임을 읽을 수 없어요")
        stamp = ", ".join(f"image {i + 1}={t}s" for i, (t, _) in enumerate(frames))
        user = f"Frames in order: {stamp}. Measured: duration {lm['duration']}s, cuts at {lm['cut_times'][:40]}, average scene {lm.get('avg_scene')}s. Infer the structure."
        res = router.run("vision", "json", system=SYSTEM, user=user, images=[f for _, f in frames], temperature=0)
    return _finish(res.value if isinstance(res.value, dict) else {}, "upload", p.name, f"{res.provider}:{res.model}:frames+local", lm, "VERIFIED")


def _url(router, url: str, notes: str) -> dict:
    from ..reference import youtube_video_id
    if youtube_video_id(url):
        if router is None or not router.has_real("vision"):
            return _result("youtube_url", url, error="영상 이해 provider(Gemini)가 연결되지 않아 YouTube 영상을 분석할 수 없어요")
        res = router.run("vision", "json", need=["youtube_url"], system=SYSTEM, user="Analyze this video's UGC ad structure.", video_url=url, temperature=0)
        return _finish(res.value if isinstance(res.value, dict) else {}, "youtube_url", url, f"{res.provider}:{res.model}:youtube_url", None, "VERIFIED")
    if notes.strip():
        return _notes(router, notes, url)
    return _result("url", url, error="이 링크는 영상을 직접 가져올 수 없어 분석할 수 없어요(Instagram/샤오홍슈/TikTok 링크 수집은 2차 범위). 영상 파일을 올리거나 구조 메모를 적어 주세요")


def _notes(router, notes: str, ref: str) -> dict:
    if router is None or not router.has_real("llm"):
        return _result("notes", ref, error="LLM 이 연결되지 않아 메모를 분석할 수 없어요")
    res = router.run("llm", "json", system=SYSTEM, user="User's notes describing a video's structure:\n" + notes[:3000], temperature=0)
    r = _finish(res.value if isinstance(res.value, dict) else {}, "notes", ref or "메모", f"{res.provider}:{res.model}:notes", None, "PARTIAL")
    if r["status"] != "FAILED":
        r["status"] = "PARTIAL"                                           # 메모 기반은 항상 부분 분석
    return r
