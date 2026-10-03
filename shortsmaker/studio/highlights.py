"""하이라이트 구간 자동 선택 (OpusClip 'ClipGenius' 방식 벤치마킹, 선택 기능·기본 OFF).

사용자가 올린 (긴) 상품 영상에서 '쓸 만한 순간'을 측정 신호로 골라낸다. 영상 편집/원본은 건드리지 않고, 구간 점수에 곱하는 보정 계수만 만든다.
신호 (있는 것만 사용, 없으면 기존 점수 그대로)
- 동작: 움직임이 적당한 순간(너무 정지/너무 흔들림 제외) — 로컬 측정
- 소리: 원본 소리가 살아있는 순간(조작음/말소리 같은 사용 신호) — 로컬 측정. 원본 소리는 결과물에 쓰지 않는다
- 제품/사용: 제품이 보이는지·사용 중인지·개인정보(얼굴/번호판 등)가 보이는지 — Vision(AI 해석, 확인 불가한 것은 쓰지 않음)
점수를 꾸미지 않고, 왜 골랐는지 측정 근거(reasons)를 함께 낸다.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np

from ..video import ffmpeg_exe

MAX_SECONDS = 240          # 하이라이트 모드는 최대 4분까지 훑는다 (기본 모드는 60초)
SAMPLE_FRAMES = 8          # 클립당 Vision 대표 프레임 수 (호출 1회)
SMOOTH = 3                 # 분석 프레임(3fps) 평활 폭

VISION_SYSTEM = ('You see frames sampled in time order from one user-shot product video. For EACH frame answer JSON only: '
                 '{"frames":[{"i":0,"product_visible":true,"in_use":false,"private_info":false}]} '
                 "product_visible: the product is clearly visible. in_use: a person is actively using/operating it (not just holding still or lying around). "
                 "private_info: a face, license plate, address, phone number, card or other personal info is readable. Do not guess; use false when unsure.")


def _smooth(a: list[float], k: int = SMOOTH) -> list[float]:
    if not a:
        return a
    arr = np.asarray(a, dtype=np.float32)
    kern = np.ones(k, dtype=np.float32) / k
    return [float(x) for x in np.convolve(arr, kern, mode="same")]


def _action(motion: list[float]) -> list[float]:
    """움직임이 적당할수록 1, 정지/급격한 변화일수록 0 (종 모양)."""
    return _smooth([math.exp(-(((m - 0.05) / 0.045) ** 2)) for m in motion])


def audio_levels(path: str, n_frames: int, fps: int, max_seconds: int = MAX_SECONDS) -> list[float] | None:
    """분석 프레임마다 0~1 소리 활동도. 소리가 없거나 거의 무음이면 None."""
    try:
        r = subprocess.run([ffmpeg_exe(), "-v", "error", "-t", str(max_seconds), "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                           capture_output=True, timeout=120)
    except Exception:
        return None
    if r.returncode != 0 or len(r.stdout) < 8000 * 4:
        return None
    x = np.frombuffer(r.stdout, dtype=np.float32)
    per = 8000 // fps
    rms = []
    for i in range(n_frames):
        seg = x[i * per:(i + 1) * per]
        rms.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    lo, hi = float(np.percentile(rms, 20)), float(np.percentile(rms, 95))
    if hi < 1e-3 or hi - lo < 1e-4:
        return None                                     # 사실상 무음/일정한 소음 → 신호로 쓰지 않는다
    return _smooth([min(1.0, max(0.0, (v - lo) / (hi - lo))) for v in rms])


def _frames(info: dict, out_dir: Path, k: int) -> list[tuple[int, str]]:
    """분석 프레임 번호와 대표 프레임 파일 (시간 순)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(info["sharp"])
    fps = info.get("fps", 3)
    res = []
    for j in range(k):
        idx = min(n - 1, int(n * (j + 0.5) / k))
        dst = out_dir / f"hl{info.get('index', 0)}_{j}.jpg"
        r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{idx / fps:.2f}", "-i", info["path"], "-an", "-frames:v", "1",
                            "-vf", "scale='min(384,iw)':-2", "-q:v", "4", str(dst)], capture_output=True)
        if r.returncode == 0 and dst.exists():
            res.append((idx, str(dst)))
    return res


def vision_marks(router, info: dict, work_dir: Path) -> dict | None:
    """{visible[], in_use[], risk[]} 분석 프레임별(계단식). Vision 이 없거나 실패하면 None."""
    if router is None or not router.has_real("vision"):
        return None
    k = max(4, min(SAMPLE_FRAMES, int(info["duration"] // 5) + 3))
    fr = _frames(info, work_dir, k)
    if len(fr) < 3:
        return None
    try:
        res = router.run("vision", "json", system=VISION_SYSTEM, user=f"{len(fr)} frames in time order.", images=[f for _, f in fr], temperature=0)
        data = res.value if isinstance(res.value, dict) else {}
    except Exception:
        return None
    rows = {int(x["i"]): x for x in (data.get("frames") or []) if isinstance(x, dict) and isinstance(x.get("i"), int)}
    if len(rows) < max(3, len(fr) // 2):
        return None
    n = len(info["sharp"])
    pts = [(idx, rows.get(j, {})) for j, (idx, _) in enumerate(fr)]
    vis, use, risk = [], [], []
    for t in range(n):
        j = min(range(len(pts)), key=lambda q: abs(pts[q][0] - t))
        row = pts[j][1]
        vis.append(1.0 if row.get("product_visible") is True else 0.0)
        use.append(1.0 if row.get("in_use") is True else 0.0)
        risk.append(1.0 if row.get("private_info") is True else 0.0)
    return {"visible": _smooth(vis), "in_use": _smooth(use), "risk": risk}


def enrich(infos: list[dict], router, work_dir: Path) -> list[str]:
    """클립 분석 결과(info)에 하이라이트 신호(info['sig'])를 붙인다. 신호를 못 만들어도 예외 없이 계속 (그 클립은 기존 점수 그대로)."""
    warnings = []
    for info in infos:
        try:
            sig = {"action": _action(info["motion"]), "sound": None, "visible": None, "in_use": None, "risk": None}
            n = len(info["sharp"])
            info.setdefault("fps", 3)
            sig["sound"] = audio_levels(info["path"], n, info["fps"])
            vm = vision_marks(router, info, work_dir / "vision")
            if vm:
                sig.update(vm)
            info["sig"] = sig
            info["sig_sources"] = ["동작(로컬)"] + (["소리(로컬)"] if sig["sound"] else []) + (["제품/사용(AI 해석)"] if vm else [])
        except Exception as e:           # 신호 실패가 영상 제작을 막지 않는다
            warnings.append(f"영상 {info.get('index', 0) + 1}: 하이라이트 신호 계산 실패({type(e).__name__}) - 기본 점수로 선택해요")
    return warnings


def _mean(a, i, win):
    seg = a[i:i + win]
    return float(np.mean(seg)) if len(seg) else 0.0


def factor(info: dict, i: int, win: int, beat: str | None = None) -> float:
    """구간 점수에 곱하는 보정 계수 (0.3~1.6). 신호가 없으면 1.0."""
    sig = info.get("sig")
    if not sig:
        return 1.0
    f = 0.8 + 0.3 * _mean(sig["action"], i, win)
    if sig.get("sound"):
        f += 0.12 * _mean(sig["sound"], i, win)
    if sig.get("visible") is not None:
        f += 0.3 * (_mean(sig["visible"], i, win) - 0.5)
        if beat in ("demo", "benefit"):
            f += 0.25 * _mean(sig["in_use"], i, win)
        if max(sig["risk"][i:i + win] or [0]) > 0.5:
            f *= 0.2                                     # 개인정보가 보이는 순간은 사실상 제외
    return max(0.3, min(1.6, f))


def explain(info: dict, start: float, dur: float, beat: str | None = None) -> list[str]:
    """고른 이유 (측정 근거). 확인 못 한 것은 말하지 않는다."""
    sig = info.get("sig")
    if not sig:
        return []
    fps = info.get("fps", 3)
    i, win = int(round(start * fps)), max(2, int(round(dur * fps)))
    out = []
    a = _mean(sig["action"], i, win)
    out.append(f"움직임이 적당해요 (동작 {a:.2f})" if a >= 0.5 else f"움직임이 약하거나 거칠어요 (동작 {a:.2f})")
    if sig.get("sound"):
        s = _mean(sig["sound"], i, win)
        if s >= 0.5:
            out.append(f"원본 소리가 살아 있어요 (소리 {s:.2f})")
    if sig.get("visible") is not None:
        if _mean(sig["visible"], i, win) >= 0.5:
            out.append("제품이 화면에 보여요 (AI 해석)")
        if _mean(sig["in_use"], i, win) >= 0.5:
            out.append("제품을 사용하는 모습이에요 (AI 해석)")
    return out


def top(info: dict, dur: float = 4.0, n: int = 3, beat: str | None = None) -> list[dict]:
    """겹치지 않는 상위 하이라이트 n 개 (미리보기/리포트용)."""
    from . import clips
    used, out = [], []
    for _ in range(n):
        w = clips.best_window(info, dur, used, beat=beat)
        if not w:
            break
        used.append((w["start"], w["start"] + w["dur"]))
        out.append({**w, "reasons": explain(info, w["start"], w["dur"], beat)})
    return out


def summary(infos: list[dict]) -> list[dict]:
    return [{"clip": Path(i["path"]).name, "duration": i["duration"], "signals": i.get("sig_sources") or ["기본 점수(선명도/밝기/흔들림)"],
             "top": top(i, 4.0, 3)} for i in infos]
