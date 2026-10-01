"""CAMERA - Motion Director 가 고른 motion id 를 시간에 따른 카메라 값(Cam)으로 바꾼다 (Renderer 쪽).

여기서는 '무엇을 쓸지' 판단하지 않는다. shot.motion 이 정해주면 그 수식대로 계산만 한다 (랜덤 없음).
"""
from __future__ import annotations

import math

from . import motion as M
from .layout_render import Cam

MOTIONS = ["zoom_in", "zoom_out", "slow_zoom", "pan_left", "pan_right", "parallax", "depth_zoom", "mask_reveal", "object_focus",
           "background_blur", "light_sweep", "floating_product", "punch_in", "shake", "ken_burns"]


def _clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def cam_at(motion: str, shot, t: float, p: float) -> Cam:
    e = M.ease(p)
    emph = getattr(shot, "emph_at", None)           # 강조 단어가 나오는 시각 (object_focus/punch 의 시작점)
    if motion == "zoom_in":
        return Cam(scale=1.0 + 0.14 * e)
    if motion == "zoom_out":
        return Cam(scale=1.14 - 0.14 * e)
    if motion == "slow_zoom":
        return Cam(scale=1.0 + 0.06 * p)
    if motion in ("pan_left", "pan_right"):
        d = 1 if motion == "pan_right" else -1
        return Cam(scale=1.12, dx=d * (-0.04 + 0.08 * e))
    if motion == "parallax":
        k = e - 0.5
        return Cam(scale=1.04, dx=0.03 * k, bg_scale=1.10, bg_dx=-0.045 * k)       # 배경은 반대로, 더 크게
    if motion == "depth_zoom":
        return Cam(scale=1.0 + 0.05 * e, bg_scale=1.0 + 0.2 * e)                  # 배경이 더 빨리 다가와 깊이감
    if motion == "mask_reveal":
        return Cam(scale=1.05 - 0.03 * e, reveal=_clamp(p / 0.5))
    if motion == "object_focus":
        on = _clamp((t - (emph if emph is not None else 0.15)) / 0.35)
        return Cam(scale=1.0 + 0.08 * e, spot=0.9 * M.ease(on), ring=M.ease(on))
    if motion == "background_blur":
        return Cam(scale=1.0 + 0.03 * p, blur=0.85 * M.ease(_clamp(t / 0.3)))
    if motion == "light_sweep":
        return Cam(scale=1.0 + 0.03 * p, sweep=_clamp((p - 0.12) / 0.7))
    if motion == "floating_product":
        return Cam(scale=1.03 + 0.02 * p, bob=0.012 * math.sin(2 * math.pi * t / 1.6))
    if motion == "punch_in":
        return Cam(scale=1.0 + 0.14 * M.ease_out(_clamp(t / 0.28)) + 0.03 * p)
    if motion == "shake":
        amp = 11.0 * (1 - p) ** 2
        return Cam(scale=1.06, shake=(amp * math.sin(t * 58), amp * 0.7 * math.cos(t * 49)))
    if motion == "ken_burns":
        return Cam(scale=1.08 + 0.06 * p, dx=0.03 - 0.06 * p, dy=0.015 - 0.03 * p)
    return Cam(scale=1.0 + 0.05 * e)            # motion 미지정(레이아웃만 있는 경우): 기본 느린 확대
