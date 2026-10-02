"""오디오: 효과음(SFX) 합성, 자체 제작 음악 베드, TTS 배치, 믹스.

음원 저작권 문제를 피하려고 음악/효과음은 코드로 직접 합성한다 (rights: OWNED).
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from ..video import ffmpeg_exe

SR = 44100
BPM = 100
BEAT = 60 / BPM


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.clip(t - attack, 0, None) / max(decay, 1e-4))


def whoosh(dur: float = 0.35) -> np.ndarray:
    n = int(dur * SR)
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 1, n)
    # 간단한 1차 필터를 시간에 따라 열어서 '쉭' 소리
    out = np.zeros(n)
    alpha = np.linspace(0.02, 0.35, n)
    acc = 0.0
    for i in range(n):
        acc += alpha[i] * (noise[i] - acc)
        out[i] = acc
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return out * env * 0.9


def hit(dur: float = 0.45) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    freq = 70 * np.exp(-t * 6) + 42
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    click = np.random.default_rng(2).normal(0, 1, n) * np.exp(-t * 90) * 0.3
    return (body * _env(n, 0.002, 0.16) + click) * 0.9


def pop(dur: float = 0.06) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = np.linspace(900, 1500, n)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.02) * 0.35


def riser(dur: float = 0.7) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = np.linspace(200, 900, n)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25
    noise = np.random.default_rng(3).normal(0, 0.25, n)
    return (tone + noise * np.linspace(0, 1, n)) * np.linspace(0, 1, n) ** 2 * 0.5


def music_bed(total: float, seed: int = 0, bpm: float = BPM, kick_gain: float = 0.8, pad_gain: float = 0.22) -> np.ndarray:
    """100BPM 로파이 느낌의 부드러운 베드 (킥 + 하이햇 + 패드). 저작권 자유."""
    n = int(total * SR) + SR
    out = np.zeros(n)
    t_all = np.arange(n) / SR
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 164.81, 196.0), (196.0, 246.94, 293.66)]
    beat = 60 / bpm
    bar = beat * 4
    for bi in range(int(total / bar) + 2):
        s = int(bi * bar * SR)
        e = min(n, int((bi + 1) * bar * SR))
        if s >= n:
            break
        tt = t_all[s:e] - bi * bar
        ch = chords[(bi + seed) % 4]
        pad = sum(np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt) for f in ch) / 6
        swell = np.clip(tt / 0.4, 0, 1) * np.clip((bar - tt) / 0.3, 0, 1)
        out[s:e] += pad * swell * pad_gain
    kick = hit(0.3) * kick_gain
    rng = np.random.default_rng(4)
    hat = rng.normal(0, 1, int(0.04 * SR)) * _env(int(0.04 * SR), 0.001, 0.012) * 0.12
    for k in range(int(total / beat) + 2):
        s = int(k * beat * SR)
        if k % 2 == 0 and kick_gain > 0:
            _add(out, kick, s)
        if kick_gain > 0:
            _add(out, hat, s + int(beat / 2 * SR))
    return out[: int(total * SR)]


def _add(track: np.ndarray, clip: np.ndarray, start: int, gain: float = 1.0) -> None:
    if start >= len(track):
        return
    start = max(start, 0)
    end = min(len(track), start + len(clip))
    track[start:end] += clip[: end - start] * gain


def decode_audio(path: str | Path) -> np.ndarray:
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def audio_duration(path: str | Path) -> float:
    return len(decode_audio(path)) / SR


def click(dur: float = 0.04) -> np.ndarray:
    """짧은 딸깍: 날카로운 노이즈 틱 + 높은 톤"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    tick = np.random.default_rng(4).normal(0, 1, n) * np.exp(-t * 220) * 0.5
    return (np.sin(2 * np.pi * 2400 * t) * _env(n, 0.0005, 0.008) * 0.35 + tick) * 0.8


def ding(dur: float = 0.6) -> np.ndarray:
    """맑은 종소리: 기본음 + 배음, 천천히 감쇠"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 1760 * t) + 0.45 * np.sin(2 * np.pi * 2640 * t) + 0.2 * np.sin(2 * np.pi * 3520 * t)
    return tone * _env(n, 0.002, 0.22) * 0.22


def impact(dur: float = 0.6) -> np.ndarray:
    """묵직한 타격: 저음 스윕 + 노이즈 버스트"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * np.cumsum(95 * np.exp(-t * 5) + 38) / SR) * _env(n, 0.002, 0.25)
    burst = np.random.default_rng(5).normal(0, 1, n) * np.exp(-t * 40) * 0.35
    return (body + burst) * 0.55


def swipe(dur: float = 0.22) -> np.ndarray:
    """가벼운 쓸어넘김: 짧은 필터 노이즈"""
    n = int(dur * SR)
    noise = np.random.default_rng(6).normal(0, 1, n)
    out, acc = np.zeros(n), 0.0
    alpha = np.linspace(0.05, 0.5, n)
    for i in range(n):
        acc += alpha[i] * (noise[i] - acc)
        out[i] = acc
    return out * np.sin(np.linspace(0, np.pi, n)) ** 1.5 * 0.7


def soft_hit(dur: float = 0.25) -> np.ndarray:
    """부드러운 쿵: 낮은 톤 + 빠른 감쇠"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(130 * np.exp(-t * 9) + 60) / SR) * _env(n, 0.003, 0.07) * 0.7


def transition_hit(dur: float = 0.35) -> np.ndarray:
    """전환 타격: hit 보다 짧고 밝게"""
    return hit(dur) * 0.8


SFX = {"whoosh": whoosh, "hit": hit, "pop": pop, "riser": riser, "click": click, "ding": ding, "impact": impact, "swipe": swipe,
       "soft_hit": soft_hit, "transition_hit": transition_hit}


def build_mix(total: float, events: list[dict], voice: list[tuple[float, str]], out: Path,
              music: bool = True, bgm_path: str | None = None, music_gain: float = 0.35, music_style: dict | None = None) -> Path:
    """events: [{"t": 초, "sfx": "whoosh"|..., "gain": 0.6}], voice: [(시작초, 파일)]"""
    n = int(total * SR)
    track = np.zeros(n)
    bed = None
    if bgm_path:
        b = decode_audio(bgm_path)
        reps = int(np.ceil(n / max(len(b), 1)))
        bed = np.tile(b, reps)[:n]
    elif music:
        ms = music_style or {}
        bed = music_bed(total, bpm=ms.get("bpm", BPM), kick_gain=ms.get("kick", 0.8), pad_gain=ms.get("pad", 0.22))
        music_gain = ms.get("gain", music_gain)
    vo = np.zeros(n)
    for start, path in voice:
        _add(vo, decode_audio(path), int(start * SR))
    if bed is not None:
        # 보이스가 있으면 음악을 덕킹
        duck = np.ones(n)
        if np.abs(vo).max() > 0:
            env = np.convolve(np.abs(vo), np.ones(4410) / 4410, mode="same")
            duck = 1 - 0.55 * np.clip(env * 12, 0, 1)
        fade = np.ones(n)
        f = int(min(1.2, total / 4) * SR)
        fade[-f:] = np.linspace(1, 0, f)
        fade[: int(0.05 * SR)] = np.linspace(0, 1, int(0.05 * SR))
        track += bed[:n] * duck * fade * music_gain
    track += vo
    for ev in events:
        fn = SFX.get(ev["sfx"])
        if fn:
            _add(track, fn(), int(ev["t"] * SR), ev.get("gain", 0.6))
    peak = np.abs(track).max()
    if peak > 0.98:
        track = track / peak * 0.98
    out = Path(out)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((track * 32767).astype(np.int16).tobytes())
    return out
