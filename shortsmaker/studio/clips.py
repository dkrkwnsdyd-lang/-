"""VIDEO CLIPS: 사용자가 직접 찍은 상품 영상 클립을 컷에 끼워 넣는다.

- 클립 전체를 3fps 로 훑어 선명도/밝기/흔들림을 점수화하고, 컷 길이에 맞는 가장 좋은 구간을 고른다.
- 원본 소리는 쓰지 않는다 (음악/효과음/보이스만). 원본 파일은 건드리지 않는다.
- 세로 영상은 꽉 채우고, 가로/정사각 영상은 흐린 배경 위에 가운데 배치한다.
- 영상에는 얼굴/번호판/주소 등이 찍힐 수 있어 Vision 으로 대표 프레임을 검사하고, 검사할 수 없으면 경고한다.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from ..video import ffmpeg_exe

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp"}
ANALYSIS_FPS = 3
MAX_ANALYZE_SECONDS = 60
MIN_USABLE = 1.0                  # 이보다 짧은 클립은 쓰지 않는다
GUARD = 1                         # 시작/끝 프레임(녹화 버튼 흔들림) 제외
MAX_CLIP_SHOTS = 3
BEAT_PRIORITY = {"demo": 0, "benefit": 1, "detail": 2, "reveal": 3}   # 사용 장면 우선 (hook/problem/cta 는 사진 유지)


# ------------------------------------------------------------------ analysis
def _lap_var(gray: np.ndarray) -> float:
    lap = (-4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:])
    return float(lap.var())


def analyze_clip(path: str | Path, work_dir: Path) -> dict:
    """{ok, path, duration, aspect, sharp[], bright[], motion[], warnings[]} - 실패해도 예외 대신 ok=False."""
    path = Path(path)
    tmp = Path(tempfile.mkdtemp(prefix="clip_", dir=work_dir))
    try:
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-t", str(MAX_ANALYZE_SECONDS), "-i", str(path),
               "-an", "-vf", f"fps={ANALYSIS_FPS},scale=192:-2", "-q:v", "3", str(tmp / "f_%04d.jpg")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        frames = sorted(tmp.glob("f_*.jpg"))
        if r.returncode != 0 or not frames:
            return {"ok": False, "path": str(path), "error": (r.stderr or "프레임을 읽을 수 없습니다")[-200:]}
        grays, sharp, bright = [], [], []
        for f in frames:
            with Image.open(f) as im:
                g = np.asarray(im.convert("L"), dtype=np.float32)
                w, h = im.size
            grays.append(g)
            sharp.append(_lap_var(g))
            bright.append(float(g.mean() / 255))
        motion = [0.0] + [float(np.abs(grays[i] - grays[i - 1]).mean() / 255) for i in range(1, len(grays))]
        duration = len(frames) / ANALYSIS_FPS
        info = {"ok": True, "path": str(path), "duration": round(duration, 2), "aspect": round(w / h, 4),
                "sharp": sharp, "bright": bright, "motion": motion, "warnings": []}
        if duration < MIN_USABLE:
            info["ok"] = False
            info["error"] = f"클립이 너무 짧습니다 ({duration:.1f}초, 최소 {MIN_USABLE:.0f}초)"
        elif float(np.percentile(sharp, 95)) < 15:
            info["warnings"].append("전체적으로 흐릿하거나 초점이 맞지 않아 보여요")
        if info["ok"] and float(np.median(bright)) < 0.18:
            info["warnings"].append("영상이 많이 어두워요")
        return info
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _window_score(info: dict, i: int, win: int) -> float:
    sharp = np.asarray(info["sharp"][i:i + win])
    ref = max(float(np.percentile(info["sharp"], 95)), 1e-6)
    sn = float(np.clip(sharp / ref, 0, 1).mean())
    b = float(np.mean(info["bright"][i:i + win]))
    bright_f = 1.0 if 0.25 <= b <= 0.85 else 0.6
    m = info["motion"][i + 1:i + win] or [0.0]
    shaky = 0.6 if max(m) > 0.25 else 1.0            # 컷 전환/급격한 흔들림 포함
    static = 0.85 if float(np.mean(m)) < 0.004 else 1.0   # 거의 정지 화면
    return sn * bright_f * shaky * static


def best_window(info: dict, dur: float, avoid: list[tuple[float, float]] | None = None) -> dict | None:
    """길이 dur 초짜리 가장 좋은 구간. 이미 쓴 구간(avoid)과는 겹치지 않는다. 못 찾으면 None."""
    n = len(info["sharp"])
    win = max(2, round(dur * ANALYSIS_FPS))
    if win > n:
        return None
    lo, hi = (GUARD, n - win - GUARD) if n - win - GUARD >= GUARD else (0, n - win)
    best = None
    for i in range(lo, hi + 1):
        s, e = i / ANALYSIS_FPS, (i + win) / ANALYSIS_FPS
        if any(s < ae and e > as_ for as_, ae in (avoid or [])):
            continue
        sc = _window_score(info, i, win)
        if best is None or sc > best["score"]:
            best = {"start": round(s, 3), "dur": round(win / ANALYSIS_FPS, 3), "score": round(sc, 3)}
    return best


def prepare(paths: list[str], work_dir: Path) -> tuple[list[dict], list[str]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    infos, warnings = [], []
    for i, p in enumerate(paths):
        info = analyze_clip(p, work_dir)
        name = Path(p).name
        if not info["ok"]:
            warnings.append(f"영상 {i + 1}: 사용할 수 없어 제외 - {info.get('error', '')}")
            continue
        info["index"] = i
        infos.append(info)
        warnings += [f"영상 {i + 1}: {w}" for w in info["warnings"]]
    return infos, warnings


def sample_frames(info: dict, out_dir: Path, count: int = 4, size: int = 720) -> list[str]:
    """개인정보 검사용 대표 프레임 (클립 전체에서 고르게)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for k in range(count):
        t = info["duration"] * (k + 0.5) / count
        dst = out_dir / f"clip{info['index']}_{k}.jpg"
        r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", info["path"], "-an",
                            "-frames:v", "1", "-vf", f"scale='min({size},iw)':-2", "-q:v", "3", str(dst)],
                           capture_output=True)
        if r.returncode == 0 and dst.exists():
            out.append(str(dst))
    return out


# ------------------------------------------------------------------ assignment
def assign(shots: list, scenes: list, infos: list[dict]) -> list[dict]:
    """사용 장면 컷(demo/benefit/detail/reveal)을 클립으로 바꾼다. 컷 길이는 그대로 (오디오/자막 타이밍 유지)."""
    if not infos:
        return []
    beat_of = {s.scene_id: s.beat for s in scenes}
    layout_mode = any(getattr(s, "layout", "") for s in shots)             # Storyboard 경로: 시연/사용 장면 레이아웃에만 영상 클립
    if layout_mode:
        cands = [s for s in shots if s.layout in ("demo", "lifestyle")]
    else:
        cands = [s for s in shots if beat_of.get(s.scene_id) in BEAT_PRIORITY]
    cands.sort(key=lambda s: (BEAT_PRIORITY.get(beat_of.get(s.scene_id), 9), -s.duration))
    used: dict[int, list[tuple[float, float]]] = {i["index"]: [] for i in infos}
    report = []
    for shot in cands:
        if len(report) >= MAX_CLIP_SHOTS:
            break
        best = None
        for info in infos:
            w = best_window(info, shot.duration, used[info["index"]])
            if w and (best is None or w["score"] > best[1]["score"]):
                best = (info, w)
        if best is None:
            continue
        info, w = best
        used[info["index"]].append((w["start"], w["start"] + w["dur"]))
        if not layout_mode:
            shot.shot = "video_clip"
        shot.source = info["path"]
        shot.clip_start = w["start"]
        shot.clip_aspect = info["aspect"]
        shot.punch_at = []
        report.append({"scene_id": shot.scene_id, "beat": beat_of[shot.scene_id], "clip": Path(info["path"]).name,
                       "start": w["start"], "dur": w["dur"], "score": w["score"]})
    return report


# ------------------------------------------------------------------ playback
class ClipReader:
    """클립의 한 구간을 W x H 프레임으로 순차 디코딩. 원본은 그대로, 필터로 9:16 에 맞춘다."""

    def __init__(self, path: str, start: float, aspect: float, width: int, height: int, fps: int):
        self.path, self.start, self.aspect = path, start, aspect
        self.w, self.h, self.fps = width, height, fps
        self.proc: subprocess.Popen | None = None
        self.pos = 0
        self.last: Image.Image | None = None
        self.eof: int | None = None            # 이 프레임 번호부터는 클립이 끝난 것

    def _filter(self) -> str:
        w, h = self.w, self.h
        if self.aspect <= 0.8:      # 세로 영상: 꽉 채우기
            return f"fps={self.fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,format=rgb24"
        return (f"fps={self.fps},split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"boxblur=24:2,eq=brightness=-0.12[bg];[b]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=rgb24")

    def _open(self, idx: int) -> None:
        self.close()
        self.eof = None
        ss = self.start + idx / self.fps
        self.proc = subprocess.Popen(
            [ffmpeg_exe(), "-loglevel", "error", "-ss", f"{ss:.3f}", "-i", self.path, "-an", "-vf", self._filter(),
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.pos = idx

    def _next(self) -> Image.Image | None:
        n = self.w * self.h * 3
        buf = self.proc.stdout.read(n) if self.proc and self.proc.stdout else b""
        if len(buf) < n:
            return None
        self.pos += 1
        return Image.frombytes("RGB", (self.w, self.h), buf)

    def read(self, idx: int) -> Image.Image:
        idx = max(0, idx)
        if self.eof is not None and idx >= self.eof:
            return self.last or Image.new("RGB", (self.w, self.h), (0, 0, 0))
        if self.proc is not None and idx == self.pos - 1 and self.last is not None:
            return self.last                   # 같은 프레임을 다시 요청
        if self.proc is None or idx < self.pos or idx - self.pos > self.fps:
            self._open(idx)
        img = None
        while self.pos <= idx:
            img = self._next()
            if img is None:                    # 클립 끝: 마지막 프레임을 유지
                self.eof = self.pos
                self.close()
                return self.last or Image.new("RGB", (self.w, self.h), (0, 0, 0))
            self.last = img
        return img if img is not None else (self.last or Image.new("RGB", (self.w, self.h), (0, 0, 0)))

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.stdout.close()
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None
