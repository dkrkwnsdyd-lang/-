"""LAYOUT RENDERER - Storyboard 의 layout(17종)을 실제 프레임으로 그린다 (Renderer 쪽).

Renderer 는 판단하지 않는다: layout / motion 은 Storyboard 가 정하고, 여기서는 그 값대로 그리기만 한다.
카메라(확대/이동/흔들림/블러/공개)는 Cam 으로 분리돼 있어 Motion Director 가 값을 채운다.
기존 motion.py 의 검증된 부품(hero parts, macro plate, spotlight, light sweep)을 재사용하고, 기존 렌더 경로는 그대로 둔다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import motion as M

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp")


@dataclass
class Cam:
    scale: float = 1.0
    dx: float = 0.0              # 프레임 폭 대비 이동 (-1~1, 실제로는 ±0.1 안팎)
    dy: float = 0.0
    blur: float = 0.0            # 배경 블러 강도 0~1 (제품 박스 바깥)
    spot: float = 0.0            # 제품 주변만 남기는 강도 0~1
    reveal: float = 1.0          # 마스크 공개 진행 0~1 (1 = 완전 공개)
    bob: float = 0.0             # 제품 상하 떠 있는 오프셋 (프레임 높이 대비)
    shake: tuple = (0, 0)        # px
    sweep: float | None = None   # 라이트 스윕 진행 0~1
    ring: float = 0.0            # 강조 링 강도 0~1
    extra: dict = field(default_factory=dict)


def default_cam(p: float) -> Cam:
    return Cam(scale=1.0 + 0.05 * M.ease(p))


# ------------------------------------------------------------------ helpers
def _wh() -> tuple[int, int]:
    return M.W, M.H


def _is_video(path: str | None) -> bool:
    return bool(path) and str(path).lower().endswith(VIDEO_EXTS)


def _region(r, path: str, aspect: float, pad: float = 0.22) -> Image.Image:
    if path in r.cache.tight:                        # 개인 정보가 찍힌 사진: 제품 주변만 사용 (넓게 자르지 않음)
        tight = r.cache.product_region(path, pad=0.03)
        if tight is not None:
            bw = 1000
            bgi = ImageOps.fit(tight, (bw, max(2, int(bw / aspect))), Image.BILINEAR).filter(ImageFilter.GaussianBlur(24))
            bgi = bgi.point(lambda v: int(v * 0.55))
            fg = ImageOps.contain(tight, (int(bw * 0.94), int(bw / aspect * 0.94)), Image.LANCZOS)
            bgi.paste(fg, ((bgi.width - fg.width) // 2, (bgi.height - fg.height) // 2))
            return bgi
    reg = r.cache.product_region(path, pad=pad, aspect=aspect)
    if reg is not None:
        return reg
    return ImageOps.fit(r.cache.source(path), (1000, max(2, int(1000 / aspect))), Image.LANCZOS)


def _plate(r, key: tuple, build) -> Image.Image:
    if key not in r.cache.plates:
        r.cache.plates[key] = build()
    return r.cache.plates[key]


def cover_plate(r, path: str, w_scale: float = 1.2, pad: float = 0.22, aspect: float | None = None, tag: str = "cover") -> Image.Image:
    W, H = _wh()
    asp = aspect or (W / H)
    pw, ph = int(W * w_scale), int(W * w_scale / asp)
    return _plate(r, (tag, path, pw, ph, pad), lambda: _region(r, path, asp, pad).resize((pw, ph), Image.LANCZOS))


def bg_plate(r, path: str, scale: float = 1.2, dark: float = 0.7) -> Image.Image:
    W, H = _wh()
    return _plate(r, ("bgp", path, scale, dark), lambda: M.blurred_background(r.cache.source(path), (int(W * scale), int(H * scale)), dark=dark))


def window(plate_size: tuple[int, int], cam: Cam, cx: float = 0.5, cy: float = 0.5) -> tuple[float, float, float, float]:
    """MotionRenderer._crop 과 같은 창 계산 (x0, y0, bw, bh) - 제품 박스를 프레임 좌표로 옮길 때도 쓴다."""
    W, H = _wh()
    pw, ph = plate_size
    base = min(pw / W, ph / H)
    bw, bh = W * base / max(cam.scale, 0.01), H * base / max(cam.scale, 0.01)
    x0 = min(max((cx + cam.dx) * pw - bw / 2, 0), pw - bw)
    y0 = min(max((cy + cam.dy) * ph - bh / 2, 0), ph - bh)
    return x0, y0, bw, bh


def cam_crop(plate: Image.Image, cam: Cam, cx: float = 0.5, cy: float = 0.5) -> Image.Image:
    W, H = _wh()
    x0, y0, bw, bh = window(plate.size, cam, cx, cy)
    return plate.transform((W, H), Image.EXTENT, (x0, y0, x0 + bw, y0 + bh), Image.BILINEAR)


def to_frame(rect_px: tuple, plate_size: tuple[int, int], cam: Cam, cx: float = 0.5, cy: float = 0.5) -> tuple:
    x0, y0, bw, bh = window(plate_size, cam, cx, cy)
    a, b, c, d = rect_px
    return ((a - x0) / bw, (b - y0) / bh, (c - x0) / bw, (d - y0) / bh)


def rounded(img: Image.Image, radius: int) -> Image.Image:
    im = img.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius, fill=255)
    im.putalpha(mask)
    return im


def shadow_under(base: Image.Image, rect: tuple, blur: int = 28, opacity: int = 150, off: int = 16) -> None:
    W, H = base.size
    x0, y0, x1, y1 = [int(v) for v in rect]
    lay = Image.new("L", base.size, 0)
    ImageDraw.Draw(lay).rounded_rectangle([x0 + off // 2, y0 + off, x1 + off // 2, y1 + off], int(W * 0.03), fill=opacity)
    base.paste(Image.new("RGB", base.size, (0, 0, 0)), (0, 0), lay.filter(ImageFilter.GaussianBlur(blur)))


def font(r, size: int):
    return M._font(r.captions.font_path, size)


def wrap(text: str, f, max_w: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > max_w and cur:
            lines.append(cur)
            cur = ch.lstrip()
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def chip(r, text: str, size: int, fill=(0, 0, 0, 170), color=(255, 255, 255, 255), pad: int | None = None) -> Image.Image:
    f = font(r, size)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    pad = pad if pad is not None else int(size * 0.5)
    tw = int(d.textlength(text, font=f))
    im = Image.new("RGBA", (tw + pad * 2, int(size * 1.35) + pad), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle([0, 0, im.width - 1, im.height - 1], int(im.height * 0.5), fill=fill)
    dd.text((pad, pad // 2 + int(size * 0.02)), text, font=f, fill=color)
    return im


def paste_rgba(base: Image.Image, im: Image.Image, xy: tuple) -> None:
    base.paste(im, (int(xy[0]), int(xy[1])), im)


def ring_overlay(frame: Image.Image, cx: float, cy: float, radius: float, strength: float, width: int = 6) -> Image.Image:
    if strength <= 0.01:
        return frame
    ov = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    a = int(255 * min(1, strength))
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(255, 225, 90, a), width=width)
    d.ellipse([cx - radius * 1.18, cy - radius * 1.18, cx + radius * 1.18, cy + radius * 1.18], outline=(255, 225, 90, a // 3), width=3)
    out = frame.convert("RGBA")
    out.alpha_composite(ov)
    return out.convert("RGB")


def _hero(r, path: str, ratio: float = 0.8, center_y: float = 0.56, scale: float = 1.2):
    return M._hero_parts(r.cache, path, scale, ratio, center_y)


def _card_with_shadow(r, path: str, scale: float = 1.2, ratio: float = 0.8, center_y: float = 0.56, bob_px: int = 0):
    """(plate, rect_px) - 배경 위에 제품 카드/컷아웃 + 그림자. bob_px 로 떠 있는 움직임."""
    bg, fg, a, (x, y) = _hero(r, path, ratio, center_y, scale)
    plate = bg.copy()
    y2 = y + bob_px
    M._with_shadow(plate, a, (x, y2), int(plate.width * 0.025), (int(plate.width * 0.012), int(plate.height * 0.018 + abs(bob_px) * 0.6)))
    plate.paste(fg, (x, y2), a)
    return plate, (x, y2, x + fg.width, y2 + fg.height)


# ------------------------------------------------------------------ layouts (frame, product_rect_in_frame)
def L_full_product(r, shot, t, p, cam):
    plate = cover_plate(r, shot.source, 1.22, 0.5)          # 맥락 넓게 (close_up 은 제품을 꽉 채움)
    return cam_crop(plate, cam), (0.2, 0.3, 0.8, 0.7)


def L_close_up(r, shot, t, p, cam):
    plate = M.macro_plate(r.cache, shot.source, shot.focus)
    return cam_crop(plate, cam), (0.12, 0.25, 0.88, 0.75)


def L_product_center(r, shot, t, p, cam):
    plate = M.hero_plate(r.cache, shot.source, fg_ratio=0.8)
    bg, fg, a, (x, y) = _hero(r, shot.source, 0.8, 0.56, 1.2)
    rect = to_frame((x, y, x + fg.width, y + fg.height), plate.size, cam)
    return cam_crop(plate, cam), rect


def L_floating_product(r, shot, t, p, cam):
    bg, fg, a, (x, y) = _hero(r, shot.source, 0.78, 0.55, 1.2)
    plate, rect_px = _card_with_shadow(r, shot.source, 1.2, 0.78, 0.55, bob_px=int(cam.bob * bg.height))
    return cam_crop(plate, cam), to_frame(rect_px, plate.size, cam)


def L_result(r, shot, t, p, cam):
    plate = M.hero_plate(r.cache, shot.source, fg_ratio=0.8)
    bg, fg, a, (x, y) = _hero(r, shot.source, 0.8, 0.56, 1.2)
    glow = _plate(r, ("glow", plate.size), lambda: _glow(plate.size))
    k = min(1.0, 0.35 + 0.65 * M.ease(p))
    lit = ImageChops.screen(plate, Image.eval(glow, lambda v: int(v * k)))
    return cam_crop(lit, cam), to_frame((x, y, x + fg.width, y + fg.height), plate.size, cam)


def _glow(size: tuple[int, int]) -> Image.Image:
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w * 0.55)) ** 2 + ((yy - h * 0.56) / (h * 0.32)) ** 2)
    g = np.clip(1.0 - d, 0, 1) ** 2 * 85
    return Image.fromarray(g.astype(np.uint8)).convert("RGB")


def L_cta(r, shot, t, p, cam):
    plate = M.hero_plate(r.cache, shot.source, fg_ratio=0.84)
    bg, fg, a, (x, y) = _hero(r, shot.source, 0.84, 0.56, 1.2)
    return cam_crop(plate, cam), to_frame((x, y, x + fg.width, y + fg.height), plate.size, cam)


def L_product_overlay(r, shot, t, p, cam):
    W, H = _wh()
    base = cam_crop(bg_plate(r, shot.source, 1.2, 0.62), cam)
    card = _region(r, shot.source, 0.78, 0.04)
    cw = int(W * 0.66)
    card = ImageOps.contain(card, (cw, int(H * 0.5)), Image.LANCZOS)
    x, y = int(W * 0.05), int(H * 0.36 + math.sin(p * math.pi) * H * 0.01)
    rc = rounded(card, int(W * 0.035))
    shadow_under(base, (x, y, x + rc.width, y + rc.height))
    paste_rgba(base, rc, (x, y))
    return base, (x / W, y / H, (x + rc.width) / W, (y + rc.height) / H)


def L_text_focus(r, shot, t, p, cam):
    W, H = _wh()
    base = cam_crop(bg_plate(r, shot.source, 1.2, 0.42), cam)
    card = ImageOps.contain(_region(r, shot.source, 0.78, 0.04), (int(W * 0.36), int(H * 0.22)), Image.LANCZOS)
    rc = rounded(card, int(W * 0.03))
    x, y = int(W * 0.58), int(H * 0.66)
    shadow_under(base, (x, y, x + rc.width, y + rc.height), blur=20, opacity=130, off=10)
    paste_rgba(base, rc, (x, y))
    return base, (x / W, y / H, (x + rc.width) / W, (y + rc.height) / H)


def L_split_screen(r, shot, t, p, cam):
    W, H = _wh()
    half = (H - 8) // 2
    top = cover_plate(r, shot.source, 1.15, 0.30, aspect=W / half, tag="splitA")
    bot = cover_plate(r, shot.source2 or shot.source, 1.15, 0.05, aspect=W / half, tag="splitB")
    ca = Cam(scale=cam.scale, dx=cam.dx, dy=cam.dy)
    cb = Cam(scale=cam.scale + 0.05, dx=-cam.dx, dy=-cam.dy)
    out = Image.new("RGB", (W, H), (245, 245, 245))
    for img, off, c in ((top, 0, ca), (bot, half + 8, cb)):
        bw = W * min(img.width / W, img.height / half) / max(c.scale, 0.01)
        bh = half * min(img.width / W, img.height / half) / max(c.scale, 0.01)
        x0 = min(max((0.5 + c.dx) * img.width - bw / 2, 0), img.width - bw)
        y0 = min(max((0.5 + c.dy) * img.height - bh / 2, 0), img.height - bh)
        out.paste(img.transform((W, half), Image.EXTENT, (x0, y0, x0 + bw, y0 + bh), Image.BILINEAR), (0, off))
    return out, (0.1, 0.12, 0.9, 0.88)


def L_before_after(r, shot, t, p, cam):
    W, H = _wh()
    before, after = shot.data.get("before") or shot.source, shot.data.get("after") or shot.source2 or shot.source
    A = cam_crop(cover_plate(r, before, 1.15, 0.2, tag="ba0"), cam)
    B = cam_crop(cover_plate(r, after, 1.15, 0.2, tag="ba1"), cam)
    x = int(W * (0.12 + 0.76 * M.ease(min(1.0, p * 1.3))))
    out = A.copy()
    out.paste(B.crop((x, 0, W, H)), (x, 0))
    d = ImageDraw.Draw(out)
    d.line([x, 0, x, H], fill=(255, 255, 255), width=5)
    d.ellipse([x - 26, H // 2 - 26, x + 26, H // 2 + 26], fill=(255, 255, 255))
    paste_rgba(out, chip(r, "BEFORE", int(W * 0.03)), (int(W * 0.05), int(H * 0.12)))
    paste_rgba(out, chip(r, "AFTER", int(W * 0.03), fill=(37, 99, 235, 220)), (int(W * 0.78), int(H * 0.12)))
    return out, (0.1, 0.25, 0.9, 0.75)


def L_problem_solution(r, shot, t, p, cam):
    W, H = _wh()
    top_h = int(H * 0.38)
    problem = cover_plate(r, shot.source, 1.15, 0.5, aspect=W / top_h, tag="psA")
    pa = problem.convert("L").convert("RGB")
    pa = ImageEnhanceDark(Image.blend(problem, pa, 0.75), 0.55).filter(ImageFilter.GaussianBlur(5))
    out = Image.new("RGB", (W, H), (22, 22, 26))
    x0 = (pa.width - W) // 2
    out.paste(pa.crop((x0, (pa.height - top_h) // 2, x0 + W, (pa.height - top_h) // 2 + top_h)), (0, 0))
    bg, fg, a, (x, y) = _hero(r, shot.source, 0.8, 0.56, 1.2)
    plate, rect_px = _card_with_shadow(r, shot.source, 1.2, 0.8, 0.56)
    sol = cam_crop(plate, cam).crop((0, int(H * 0.30), W, H))
    out.paste(sol, (0, top_h - int(H * 0.04)))
    d = ImageDraw.Draw(out)
    cy = top_h - int(H * 0.02)
    for k in range(3):
        yy = cy - 20 + k * 20
        d.line([(W // 2 - 26, yy), (W // 2, yy + 14), (W // 2 + 26, yy)], fill=(255, 255, 255, 200), width=5)
    paste_rgba(out, chip(r, "문제", int(W * 0.032), fill=(180, 40, 40, 220)), (int(W * 0.05), int(H * 0.05)))
    paste_rgba(out, chip(r, "해결", int(W * 0.032), fill=(22, 163, 74, 230)), (int(W * 0.05), top_h + int(H * 0.03)))
    return out, (0.1, 0.45, 0.9, 0.88)


def ImageEnhanceDark(img: Image.Image, k: float) -> Image.Image:
    return Image.eval(img, lambda v: int(v * k))


def L_feature_callout(r, shot, t, p, cam):
    W, H = _wh()
    base = cam_crop(bg_plate(r, shot.source, 1.2, 0.6), cam)
    card = ImageOps.contain(_region(r, shot.source, 0.8, 0.04), (int(W * 0.84), int(H * 0.5)), Image.LANCZOS)
    rc = rounded(card, int(W * 0.035))
    x, y = int(W * 0.04), int(H * 0.34)
    shadow_under(base, (x, y, x + rc.width, y + rc.height))
    paste_rgba(base, rc, (x, y))
    cx, cy = x + rc.width * 0.5, y + rc.height * 0.5
    pulse = 0.55 + 0.45 * math.sin(t * 7)
    out = ring_overlay(base, cx, cy, min(rc.width, rc.height) * 0.36, 0.9 * max(cam.ring, 0.5 + 0.3 * pulse), 7)
    label = shot.data.get("callout") or shot.label or ""
    if label:
        lb = chip(r, label, int(W * 0.05), fill=(255, 255, 255, 235), color=(20, 20, 24, 255))
        lx, ly = int(W * 0.50), int(H * 0.24)
        d = ImageDraw.Draw(out)
        d.line([(cx + min(rc.width, rc.height) * 0.28, cy - min(rc.width, rc.height) * 0.28), (lx + lb.width * 0.2, ly + lb.height)], fill=(255, 225, 90), width=5)
        paste_rgba(out, lb, (min(lx, W - lb.width - int(W * 0.04)), ly))
    return out, (x / W, y / H, (x + rc.width) / W, (y + rc.height) / H)


def L_three_benefits(r, shot, t, p, cam):
    W, H = _wh()
    base = cam_crop(bg_plate(r, shot.source, 1.2, 0.55), cam)
    card = ImageOps.contain(_region(r, shot.source, 0.9, 0.04), (int(W * 0.7), int(H * 0.34)), Image.LANCZOS)
    rc = rounded(card, int(W * 0.03))
    x, y = (W - rc.width) // 2, int(H * 0.1)
    shadow_under(base, (x, y, x + rc.width, y + rc.height), blur=22, off=12)
    paste_rgba(base, rc, (x, y))
    items = (shot.data.get("items") or [])[:3]
    top = int(H * 0.56)
    for i, text in enumerate(items):
        t0 = 0.15 + 0.3 * i
        if t < t0:
            continue
        k = min(1.0, (t - t0) / 0.18)
        c = chip(r, text, int(W * 0.06), fill=(255, 255, 255, int(235 * k)), color=(20, 24, 32, int(255 * k)))
        xx = int(W * 0.06 + (1 - M.ease_out(k)) * W * 0.25)
        yy = top + i * int(H * 0.11)
        paste_rgba(base, c, (xx, yy))
        d = ImageDraw.Draw(base)
        rr = int(W * 0.022)
        d.ellipse([xx - rr * 2.3, yy + c.height // 2 - rr, xx - rr * 0.3, yy + c.height // 2 + rr], fill=(22, 163, 74))
        d.line([(xx - rr * 1.9, yy + c.height // 2), (xx - rr * 1.3, yy + c.height // 2 + rr * 0.5), (xx - rr * 0.7, yy + c.height // 2 - rr * 0.5)], fill=(255, 255, 255), width=4)
    return base, (x / W, y / H, (x + rc.width) / W, (y + rc.height) / H)


def L_review_quote(r, shot, t, p, cam):
    W, H = _wh()
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    top, bot = np.array([18, 24, 48], np.float32), np.array([42, 52, 96], np.float32)
    out = Image.fromarray((top * (1 - yy) + bot * yy).repeat(W, axis=1).astype(np.uint8))
    d = ImageDraw.Draw(out)
    d.text((int(W * 0.07), int(H * 0.16)), "“", font=font(r, int(W * 0.3)), fill=(255, 255, 255, 60))
    f = font(r, int(W * 0.07))
    lines = wrap(shot.data.get("quote", ""), f, int(W * 0.82))[:6]
    k = min(1.0, t / 0.4)
    for i, ln in enumerate(lines):
        d.text((int(W * 0.09), int(H * 0.30 + i * W * 0.1)), ln, font=f, fill=(255, 255, 255, int(255 * k)))
    th = ImageOps.fit(r.cache.source(shot.source), (int(W * 0.2), int(W * 0.2)), Image.LANCZOS)
    m = Image.new("L", th.size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, th.width - 1, th.height - 1], fill=255)
    out.paste(th, (int(W * 0.1), int(H * 0.72)), m)
    paste_rgba(out, chip(r, "실제 후기", int(W * 0.034), fill=(255, 255, 255, 40)), (int(W * 0.36), int(H * 0.755)))
    return out, (0.1, 0.72, 0.3, 0.82)


def L_comparison(r, shot, t, p, cam):
    W, H = _wh()
    out = Image.new("RGB", (W, H), (240, 242, 247))
    d = ImageDraw.Draw(out)
    card = ImageOps.contain(_region(r, shot.source, 0.9, 0.04), (int(W * 0.42), int(H * 0.2)), Image.LANCZOS)
    paste_rgba(out, rounded(card, int(W * 0.03)), (int(W * 0.05), int(H * 0.12)))
    paste_rgba(out, chip(r, "이 제품", int(W * 0.04), fill=(37, 99, 235, 235)), (int(W * 0.55), int(H * 0.12)))
    paste_rgba(out, chip(r, "비교", int(W * 0.04), fill=(120, 120, 130, 230)), (int(W * 0.78), int(H * 0.12)))
    f = font(r, int(W * 0.045))
    for i, row in enumerate((shot.data.get("rows") or [])[:5]):
        if t < 0.1 + 0.18 * i:
            continue
        y = int(H * 0.36 + i * H * 0.1)
        d.rounded_rectangle([int(W * 0.04), y, int(W * 0.96), y + int(H * 0.08)], 18, fill=(255, 255, 255))
        d.text((int(W * 0.07), y + 18), str(row.get("label", "")), font=f, fill=(60, 64, 80))
        d.text((int(W * 0.55), y + 18), str(row.get("ours", "")), font=f, fill=(37, 99, 235))
        d.text((int(W * 0.78), y + 18), str(row.get("other", "")), font=f, fill=(120, 120, 130))
    return out, (0.05, 0.12, 0.45, 0.32)


def L_lifestyle(r, shot, t, p, cam):
    W, H = _wh()
    if _is_video(shot.source):
        frame = r._clip_frame(shot, t)
        if cam.scale > 1.001:
            frame = r._crop(frame, cam.scale, 0.5 + cam.dx, 0.5 + cam.dy)
    else:
        frame = cam_crop(cover_plate(r, shot.source, 1.22, 0.3), cam)
    vig = M._vignette_cached(W, H)
    return Image.composite(frame, Image.new("RGB", frame.size, (10, 10, 12)), vig.point(lambda v: int(255 - (255 - v) * 0.6))), (0.12, 0.25, 0.88, 0.75)


def L_demo(r, shot, t, p, cam):
    frame, rect = L_lifestyle(r, shot, t, p, cam)
    W, H = _wh()
    bar = int(W * (0.1 + 0.8 * p))
    ImageDraw.Draw(frame).rounded_rectangle([int(W * 0.1), int(H * 0.915), bar, int(H * 0.922)], 4, fill=(255, 225, 90))
    return frame, rect


L_TEXT = {  # 설명용
}

RENDERERS = {"full_product": L_full_product, "product_center": L_product_center, "split_screen": L_split_screen,
             "before_after": L_before_after, "problem_solution": L_problem_solution, "feature_callout": L_feature_callout,
             "review_quote": L_review_quote, "three_benefits": L_three_benefits, "comparison": L_comparison, "close_up": L_close_up,
             "lifestyle": L_lifestyle, "product_overlay": L_product_overlay, "floating_product": L_floating_product,
             "text_focus": L_text_focus, "demo": L_demo, "result": L_result, "cta": L_cta}


# ------------------------------------------------------------------ fx (Motion Director 가 정한 카메라 효과)
def apply_fx(r, frame: Image.Image, rect: tuple | None, cam: Cam) -> Image.Image:
    W, H = frame.size
    if rect and (cam.spot > 0.02 or cam.blur > 0.02):
        s = max(cam.spot, cam.blur)
        frame = _spot(frame, rect, 1.5 - 0.3 * s, dim=1.0 - 0.25 * s, blur_k=0.4 + 0.9 * s)
    if cam.reveal < 0.999 and rect:
        frame = _reveal(frame, rect, cam.reveal)
    if cam.sweep is not None:
        frame = r._light_sweep(frame, cam.sweep)
    if cam.shake != (0, 0):
        frame = ImageChops.offset(frame, int(cam.shake[0]), int(cam.shake[1]))
    return frame


def _spot(frame: Image.Image, rect: tuple, expand: float, dim: float, blur_k: float) -> Image.Image:
    w, h = frame.size
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max((x1 - x0) / 2 * expand, 0.06), max((y1 - y0) / 2 * expand, 0.06)
    sw, sh = 96, max(16, int(96 * h / w))
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    d = np.sqrt(((xx / sw - cx) / rx) ** 2 + ((yy / sh - cy) / ry) ** 2)
    m = np.clip((d - 1.0) / 0.5, 0, 1)
    mask = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)).resize((w, h), Image.BILINEAR)
    bg = frame.filter(ImageFilter.GaussianBlur(max(w, h) / 90 * blur_k)).point(lambda v: int(v * dim))
    return Image.composite(bg, frame, mask)


def _reveal(frame: Image.Image, rect: tuple, k: float) -> Image.Image:
    """마스크 공개: 제품 중심에서 원이 커지며 선명한 화면이 드러난다 (처음엔 어둡고 흐릿)."""
    w, h = frame.size
    cx, cy = (rect[0] + rect[2]) / 2 * w, (rect[1] + rect[3]) / 2 * h
    rad = (0.05 + 1.1 * M.ease(k)) * math.hypot(w, h) / 2
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(8, int(rad * 0.12))))
    veil = frame.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.35))
    return Image.composite(frame, veil, mask)


# ------------------------------------------------------------------ entry
def draw(r, shot, t: float) -> Image.Image:
    """layout 으로 한 프레임. 자막/전환/라벨은 MotionRenderer.frame 이 이어서 얹는다."""
    p = min(max(t / max(shot.duration, 1e-6), 0), 1)
    cam = default_cam(p)
    cam_fn = getattr(r, "cam_for", None)
    if cam_fn is not None:
        cam = cam_fn(shot, t, p) or cam
    fn = RENDERERS.get(shot.layout)
    if fn is None:
        raise ValueError(f"알 수 없는 layout: {shot.layout}")
    frame, rect = fn(r, shot, t, p, cam)
    return apply_fx(r, frame, rect, cam)
