"""HIGH QUALITY IMAGE MOTION 렌더러.

원본 제품 사진을 '움직이는' 방식이라 제품 형태/색/로고가 절대 바뀌지 않는다 (PRODUCT LOCK 100%).
단순 슬라이드쇼가 아니라 샷 타입별로 다른 플레이트와 카메라 움직임을 만든다.

shot types: punch_in, macro, whip_reveal, hero_push, detail_pan, parallax, light_sweep,
            rack_focus, problem_card, cta_card
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .. import brain
from ..video import ffmpeg_exe
from .product import cutout, product_mask

W, H, FPS = 1080, 1920, 30

CAPTION_FONTS = [
    "/usr/share/fonts/truetype/pretendard/Pretendard-ExtraBold.otf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumSquareB.ttf",
    "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def caption_font_path(preferred: str | None = None) -> str | None:
    for c in [preferred, *CAPTION_FONTS]:
        if c and Path(c).exists():
            return c
    return None


@lru_cache(maxsize=64)
def _font(path: str | None, size: int) -> ImageFont.ImageFont:
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


# ------------------------------------------------------------------ EDL

@dataclass
class CaptionWord:
    text: str
    start: float           # shot 기준 초
    emphasis: bool = False
    line: int = 0


@dataclass
class Shot:
    scene_id: str
    shot: str
    source: str
    duration: float
    caption_words: list[CaptionWord] = field(default_factory=list)
    transition_in: str = "cut"          # cut | whip | flash
    punch_at: list[float] = field(default_factory=list)  # shot 기준 punch zoom 시점
    zoom: tuple[float, float] = (1.0, 1.08)
    pan: tuple[float, float] = (0.0, 0.0)  # 이동 방향 (x, y) -1~1
    focus: tuple[float, float] | None = None  # macro 중심 (0~1)
    grade: str = "normal"               # normal | problem
    caption_zone: str = "top"           # top | bottom
    speed: float = 1.0
    label: str = ""                     # 좌상단 고지 라벨 (예: 광고)
    clip_start: float = 0.0             # shot == "video_clip": 원본 영상에서 쓸 구간 시작(초)
    clip_aspect: float = 0.5625         # 원본 영상 가로/세로 비율


# ------------------------------------------------------------------ plates

class PlateCache:
    def __init__(self):
        self.boxes: dict[str, tuple[float, float, float, float]] = {}   # 제품 위치를 아는 사진만
        self.tight: set[str] = set()      # 개인 정보가 찍힌 사진: 제품 박스 주변 밖은 절대 보이지 않게
        self.src: dict[str, Image.Image] = {}
        self.cut: dict[str, Image.Image | None] = {}
        self.plates: dict[tuple, Image.Image] = {}

    def source(self, path: str) -> Image.Image:
        if path not in self.src:
            with Image.open(path) as im:
                self.src[path] = ImageOps.exif_transpose(im).convert("RGB")
        return self.src[path]

    def product_region(self, path: str, pad: float = 0.05, aspect: float | None = None) -> Image.Image | None:
        """제품 위치를 알면 제품 주변만 잘라낸 이미지 (원본 해상도).
        aspect(가로/세로)를 주면 제품 중심으로 그 비율까지 주변을 넓혀서 세로 화면에 어울리게 한다."""
        box = self.boxes.get(path)
        if not box:
            return None
        src = self.source(path)
        w, h = src.size
        x0, y0, x1, y1 = box
        if aspect:
            bw, bh = (x1 - x0) * w * (1 + pad), (y1 - y0) * h * (1 + pad)
            cw = max(bw, bh * aspect)
            ch = cw / aspect
            if cw > w:
                cw, ch = w, w / aspect
            if ch > h:
                ch, cw = h, h * aspect
            cx, cy = (x0 + x1) / 2 * w, (y0 + y1) / 2 * h
            left = min(max(cx - cw / 2, 0), w - cw)
            top = min(max(cy - ch / 2, 0), h - ch)
            return src.crop((int(left), int(top), int(left + cw), int(top + ch)))
        return src.crop((int(max(0, x0 - pad) * w), int(max(0, y0 - pad * 0.7) * h),
                         int(min(1, x1 + pad) * w), int(min(1, y1 + pad * 0.7) * h)))

    def cutout(self, path: str) -> Image.Image | None:
        if path not in self.cut:
            self.cut[path] = cutout(self.source(path))
        return self.cut[path]


def studio_background(color_rgb: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    """제품 대표색 기반 부드러운 스튜디오 배경 (그라디언트 + 바닥 빛)."""
    w, h = size
    base = np.array(color_rgb, dtype=np.float32)
    lum = base.mean()
    # 너무 밝거나 어두운 제품이면 대비되는 톤으로
    tone = base * 0.35 + (np.array([236, 232, 226]) if lum < 110 else np.array([38, 40, 46])) * 0.65
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h * 0.58
    r = np.sqrt(((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2)
    light = np.clip(1.18 - r * 1.25, 0.55, 1.18)[..., None]
    img = np.clip(tone * light, 0, 255)
    return Image.fromarray(img.astype(np.uint8))


def blurred_background(src: Image.Image, size: tuple[int, int], dark: float = 0.62) -> Image.Image:
    small = ImageOps.fit(src, (size[0] // 8, size[1] // 8), Image.BILINEAR)
    bg = small.filter(ImageFilter.GaussianBlur(4)).resize(size, Image.BILINEAR)
    bg = ImageEnhance.Color(bg).enhance(1.15)
    return Image.eval(bg, lambda v: int(v * dark + 10))


def drop_shadow(alpha: Image.Image, blur: int = 30, opacity: int = 150) -> Image.Image:
    sh = alpha.point(lambda a: a * opacity // 255).filter(ImageFilter.GaussianBlur(blur))
    return sh


def vignette(size: tuple[int, int], strength: float = 0.35) -> Image.Image:
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    m = np.clip(1 - strength * np.clip(r - 0.55, 0, None) ** 1.5, 0, 1)
    return Image.fromarray((m * 255).astype(np.uint8))


@lru_cache(maxsize=4)
def _vignette_cached(w: int, h: int) -> Image.Image:
    return vignette((w, h))


def _hero_parts(cache: PlateCache, path: str, scale: float, fg_ratio: float, center_y: float):
    """(배경, 전경, 전경 알파, 위치) - 히어로/패럴랙스 공통."""
    key = ("parts", path, scale, fg_ratio, center_y)
    if key in cache.plates:
        return cache.plates[key]
    pw, ph = int(W * scale), int(H * scale)
    src = cache.source(path)
    cut = cache.cutout(path)
    if cut is not None:
        if path in cache.boxes:   # 사용자가 지정한 제품만 (예: 묶음 사진에서 대표 1개)
            bx0, by0, bx1, by1 = cache.boxes[path]
            cw, chh = cut.size
            cut = cut.crop((int(bx0 * cw), int(by0 * chh), int(bx1 * cw), int(by1 * chh)))
        bbox = cut.getchannel("A").getbbox() or (0, 0, *cut.size)
        fg = cut.crop(bbox)
        colors = np.asarray(fg.convert("RGB").resize((32, 32))).reshape(-1, 3)
        alpha = np.asarray(fg.getchannel("A").resize((32, 32))).reshape(-1) > 128
        dom = tuple(int(c) for c in (colors[alpha].mean(axis=0) if alpha.any() else colors.mean(axis=0)))
        bg = studio_background(dom, (pw, ph))
    else:
        fg = cache.product_region(path, pad=0.04, aspect=None if path in cache.tight else 0.78) or src
        bg = blurred_background(src, (pw, ph))
    v = _vignette_cached(pw, ph)
    bg = Image.composite(bg, Image.new("RGB", bg.size, (0, 0, 0)), v)
    # 배경 제거를 못 쓰는 사진은 원본 카드를 크게 (제품이 화면에서 작아 보이지 않게)
    box_h = 0.52 if cut is not None else 0.66
    box_w = fg_ratio if cut is not None else max(fg_ratio, 0.92)
    if cut is None:
        center_y = min(center_y, 0.53)
    fg_fit = ImageOps.contain(fg, (int(pw * box_w), int(ph * box_h)), Image.LANCZOS)
    if fg_fit.mode == "RGBA":
        a = fg_fit.getchannel("A")
        fg_rgb = fg_fit.convert("RGB")
    else:  # 복잡한 배경 사진: 둥근 모서리 카드
        a = Image.new("L", fg_fit.size, 0)
        ImageDraw.Draw(a).rounded_rectangle([0, 0, fg_fit.width - 1, fg_fit.height - 1], int(pw * 0.03), fill=255)
        fg_rgb = fg_fit
    x = (pw - fg_fit.width) // 2
    y = int(ph * center_y - fg_fit.height / 2)
    cache.plates[key] = (bg, fg_rgb, a, (x, y))
    return cache.plates[key]


def _with_shadow(base: Image.Image, alpha: Image.Image, pos: tuple[int, int], blur: int, offset: tuple[int, int]):
    shadow = drop_shadow(alpha, blur=blur, opacity=160)
    floor = Image.new("L", base.size, 0)
    floor.paste(shadow, (pos[0] + offset[0], pos[1] + offset[1]))
    base.paste(Image.new("RGB", base.size, (0, 0, 0)), (0, 0), floor)


def hero_plate(cache: PlateCache, path: str, scale: float = 1.2, fg_ratio: float = 0.8,
               center_y: float = 0.56) -> Image.Image:
    """제품을 가운데 둔 히어로 플레이트 (스튜디오 배경 + 그림자)."""
    key = ("hero", path, scale, fg_ratio, center_y)
    if key not in cache.plates:
        bg, fg, a, (x, y) = _hero_parts(cache, path, scale, fg_ratio, center_y)
        plate = bg.copy()
        _with_shadow(plate, a, (x, y), int(plate.width * 0.025), (int(plate.width * 0.012), int(plate.height * 0.018)))
        plate.paste(fg, (x, y), a)
        cache.plates[key] = plate
    return cache.plates[key]


def _studio_version(cache: PlateCache, path: str) -> Image.Image:
    """단색 배경 사진이면 배경을 히어로와 같은 스튜디오 톤으로 교체한 원본 해상도 이미지."""
    key = ("studio_src", path)
    if key in cache.plates:
        return cache.plates[key]
    src = cache.source(path)
    cut = cache.cutout(path)
    if cut is None:
        cache.plates[key] = src
        return src
    colors = np.asarray(cut.convert("RGB").resize((32, 32))).reshape(-1, 3)
    alpha = np.asarray(cut.getchannel("A").resize((32, 32))).reshape(-1) > 128
    dom = tuple(int(c) for c in (colors[alpha].mean(axis=0) if alpha.any() else colors.mean(axis=0)))
    bg = studio_background(dom, (max(64, src.width // 4), max(64, src.height // 4))).resize(src.size, Image.BILINEAR)
    bg.paste(cut.convert("RGB"), (0, 0), cut.getchannel("A"))
    cache.plates[key] = bg
    return bg


def macro_plate(cache: PlateCache, path: str, focus: tuple[float, float] | None) -> Image.Image:
    """원본 해상도에서 디테일 부분을 9:16 으로 잘라낸 플레이트 (업스케일 최소화)."""
    key = ("macro", path, focus)
    if key in cache.plates:
        return cache.plates[key]
    src = (cache.product_region(path, pad=0.03) if path in cache.tight else None) or _studio_version(cache, path)
    sw, sh = src.size
    if path in cache.tight and path in cache.boxes:   # 잘라낸 영역 기준 좌표로 초점을 중앙에
        focus = (0.5, 0.5)
    if focus is None and path in cache.boxes:
        x0, y0, x1, y1 = cache.boxes[path]
        focus = ((x0 + x1) / 2, (y0 + y1) / 2)
    if focus is None:
        focus = detail_focus(cache.source(path))
    # 제품 폭의 약 45% 정도를 화면 폭으로
    crop_w = max(int(min(sw, sh * 9 / 16) * 0.55), 64)
    if path in cache.boxes:   # 제품 폭에 맞춰 (제품이 화면 폭을 채우도록)
        crop_w = max(64, min(int((cache.boxes[path][2] - cache.boxes[path][0]) * sw * 0.62), int(sh * 9 / 16)))
    crop_h = int(crop_w * 16 / 9)
    if crop_h > sh:
        crop_h = sh
        crop_w = int(crop_h * 9 / 16)
    cx = min(max(focus[0] * sw, crop_w / 2), sw - crop_w / 2)
    cy = min(max(focus[1] * sh, crop_h / 2), sh - crop_h / 2)
    region = src.crop((int(cx - crop_w / 2), int(cy - crop_h / 2), int(cx + crop_w / 2), int(cy + crop_h / 2)))
    out_w = int(W * 1.15)
    plate = region.resize((out_w, int(out_w * 16 / 9)), Image.LANCZOS)
    plate = plate.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    cache.plates[key] = plate
    return plate


def detail_focus(src: Image.Image) -> tuple[float, float]:
    """제품 영역 안에서 가장 디테일(엣지)이 많은 지점."""
    g = np.asarray(ImageOps.contain(src, (160, 160)).convert("L")).astype(np.float32)
    mask, _ = product_mask(src, size=160)
    mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize((g.shape[1], g.shape[0]))) > 0
    gy, gx = np.gradient(g)
    e = np.hypot(gx, gy) * (mask if mask.any() else 1)
    k = 15
    pad = np.pad(e, k, mode="edge")
    cs = pad.cumsum(0).cumsum(1)
    s = cs[2 * k:, 2 * k:] - cs[:-2 * k, 2 * k:] - cs[2 * k:, :-2 * k] + cs[:-2 * k, :-2 * k]
    s = s[:g.shape[0], :g.shape[1]]
    y, x = np.unravel_index(np.argmax(s), s.shape)
    return (x / g.shape[1], y / g.shape[0])


def pan_plate(cache: PlateCache, path: str) -> Image.Image:
    """좌우로 훑는 슬라이더 샷용 가로로 긴 플레이트."""
    key = ("pan", path)
    if key in cache.plates:
        return cache.plates[key]
    raw = cache.source(path)
    mask, kind = product_mask(raw)
    src = _studio_version(cache, path)
    ys, xs = np.nonzero(mask)
    region_box = cache.product_region(path, pad=0.03)
    if region_box is not None:
        kind = "boxed"
    sw, sh = src.size
    if kind == "plain" and len(xs):
        x0, x1 = np.percentile(xs, [2, 98]) / mask.shape[1] * sw
        y0, y1 = np.percentile(ys, [2, 98]) / mask.shape[0] * sh
        pad = 0.08
        region = src.crop((max(0, int(x0 - pad * sw)), max(0, int(y0 - pad * sh)),
                           min(sw, int(x1 + pad * sw)), min(sh, int(y1 + pad * sh))))
    elif kind == "boxed":
        region = region_box
    else:
        region = src
    target_h = int(H * 1.08)
    scale = target_h / region.height
    plate = region.resize((max(int(region.width * scale), int(W * 1.3)), target_h), Image.LANCZOS)
    if plate.width < W * 1.3:
        plate = ImageOps.fit(plate, (int(W * 1.3), target_h), Image.LANCZOS)
    cache.plates[key] = plate
    return plate


# ------------------------------------------------------------------ captions

class CaptionRenderer:
    def __init__(self, font_path: str | None, safe: dict):
        self.rules = brain.system("caption_rules")
        self.font_path = caption_font_path(font_path)
        self.safe = safe
        self.cache: dict[tuple, Image.Image] = {}

    BASE_SIZE = 0.084

    def fit_size(self, lines: list[list[CaptionWord]]) -> int:
        """가장 긴 줄이 안전영역 폭에 들어가도록 글자 크기 자동 축소."""
        size = int(W * self.BASE_SIZE)
        max_w = W * (1 - self.safe["left"] - self.safe["right"]) * 0.96
        d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        widest = 0.0
        for line in lines:
            wsum = sum(d.textlength(w.text, font=_font(self.font_path, int(size * (1.14 if w.emphasis else 1))))
                       for w in line) + size * 0.4 * (len(line) - 1)
            widest = max(widest, wsum)
        scale = min(1.0, max_w / widest) if widest else 1.0
        self.last_scale = min(getattr(self, "last_scale", 1.0), scale)
        return max(24, int(size * scale))

    def layout(self, words: list[CaptionWord]) -> list[list[CaptionWord]]:
        lines: dict[int, list[CaptionWord]] = {}
        for w in words:
            lines.setdefault(w.line, []).append(w)
        return [lines[k] for k in sorted(lines)]

    def render(self, key: tuple, words: list[CaptionWord], visible: int, pop: float,
               zone: str) -> tuple[Image.Image, tuple[int, int]] | None:
        """visible 개 단어까지 보이는 자막 레이어. pop: 마지막 단어 팝 진행도(0~1)."""
        if visible <= 0:
            return None
        pstep = min(3, int(pop * 4))
        ck = (key, visible, pstep, zone)
        if ck in self.cache:
            return self.cache[ck]
        lines = self.layout(words)
        size = self.fit_size(lines)
        emph_size = int(size * 1.14)
        stroke = max(3, int(size * self.rules["stroke"]))
        line_h = int(emph_size * 1.28)
        canvas_h = line_h * len(lines) + stroke * 4 + 40
        img = Image.new("RGBA", (W, canvas_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        base = self.rules["base_color"]
        emph = self.rules["emphasis_color"]
        idx = 0
        for li, line in enumerate(lines):
            fonts = [_font(self.font_path, emph_size if w.emphasis else size) for w in line]
            space = int(size * 0.4)
            widths = [d.textlength(w.text, font=f) for w, f in zip(line, fonts)]
            total = sum(widths) + space * (len(line) - 1)
            left, right = W * self.safe["left"], W * (1 - self.safe["right"])
            x = left + (right - left - total) / 2
            y = 20 + li * line_h + line_h
            for w, f, wd in zip(line, fonts, widths):
                if idx >= visible:
                    break
                is_new = idx == visible - 1 and pstep < 3
                if is_new:
                    # 팝: 새 단어는 살짝 크게 시작해서 제자리로
                    s = 1.0 + (0.12 * (1 - pstep / 3))
                    f2 = _font(self.font_path, int((emph_size if w.emphasis else size) * s))
                    wd2 = d.textlength(w.text, font=f2)
                    d.text((x + wd / 2 - wd2 / 2, y), w.text, font=f2, anchor="ls",
                           fill=emph if w.emphasis else base, stroke_width=stroke, stroke_fill=(0, 0, 0))
                else:
                    d.text((x, y), w.text, font=f, anchor="ls", fill=emph if w.emphasis else base,
                           stroke_width=stroke, stroke_fill=(0, 0, 0))
                x += wd + space
                idx += 1
        if zone == "top":
            y0 = int(H * max(self.safe["top"], 0.12)) + 10
        else:
            y0 = int(H * (1 - max(self.safe["bottom"], 0.22))) - canvas_h - 10
        # 가독성: 자막 뒤 은은한 그림자 띠
        shadow = img.getchannel("A").filter(ImageFilter.GaussianBlur(18)).point(lambda a: a * 90 // 255)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.putalpha(shadow)
        layer.alpha_composite(img)
        self.cache[ck] = (layer, (0, y0))
        return self.cache[ck]


def split_caption(caption: str, max_chars: int = 13, max_lines: int = 2) -> list[CaptionWord]:
    """'[[강조]]' 표시를 해석하고 최대 2줄로 나눈다. 명시적 줄바꿈 우선."""
    import re
    words: list[CaptionWord] = []
    line_no = -1
    for raw in caption.split("\n"):
        tokens: list[tuple[str, bool]] = []
        for part in [p for p in re.split(r"(\[\[.+?\]\])", raw) if p.strip()]:
            if part.startswith("[["):
                tokens += [(t, True) for t in part[2:-2].split()]
            else:
                tokens += [(t, False) for t in part.split()]
        merged: list[tuple[str, bool]] = []
        for text, em in tokens:   # 문장부호만 있는 토큰은 앞 단어에 붙인다
            if merged and re.fullmatch(r"[?!.,~…]+", text):
                merged[-1] = (merged[-1][0] + text, merged[-1][1])
            else:
                merged.append((text, em))
        if not merged:
            continue
        line_no = min(line_no + 1, max_lines - 1)
        count = 0
        for text, em in merged:
            if count and count + len(text) > max_chars and line_no < max_lines - 1:
                line_no += 1
                count = 0
            words.append(CaptionWord(text, 0.0, em, line_no))
            count += len(text) + 1
    return words


# ------------------------------------------------------------------ frame renderer

class MotionRenderer:
    def __init__(self, font_path: str | None = None, safe: dict | None = None, width: int = W,
                 height: int = H, fps: int = FPS):
        global W, H
        W, H = width, height
        self.fps = fps
        self.cache = PlateCache()
        self.safe = safe or brain.system("platform_rules")["master_safe_zone"]
        self.captions = CaptionRenderer(font_path, self.safe)
        self._sweep = None
        self._label_cache: dict[str, Image.Image] = {}
        self._clips: dict[tuple, "ClipReader"] = {}

    def _clip_frame(self, shot: Shot, t: float) -> Image.Image:
        from .clips import ClipReader
        key = (shot.source, round(shot.clip_start, 3))
        rd = self._clips.get(key)
        if rd is None:
            rd = self._clips[key] = ClipReader(shot.source, shot.clip_start, shot.clip_aspect, W, H, self.fps)
        return rd.read(int(t * self.fps + 1e-6))

    def close_clips(self) -> None:
        for rd in self._clips.values():
            rd.close()
        self._clips.clear()

    # --- camera helpers
    @staticmethod
    def _crop(plate: Image.Image, scale: float, cx: float, cy: float) -> Image.Image:
        """plate 에서 (W,H) 비율 창을 scale 배율로 잘라 출력 크기로."""
        pw, ph = plate.size
        base = min(pw / W, ph / H)
        bw, bh = W * base / scale, H * base / scale
        x0 = min(max(cx * pw - bw / 2, 0), pw - bw)
        y0 = min(max(cy * ph - bh / 2, 0), ph - bh)
        return plate.transform((W, H), Image.EXTENT, (x0, y0, x0 + bw, y0 + bh), Image.BILINEAR)

    def _light_sweep(self, frame: Image.Image, p: float) -> Image.Image:
        if self._sweep is None:
            band = np.zeros((H, W * 2), np.float32)
            xs = np.arange(W * 2, dtype=np.float32)
            band += np.exp(-((xs - W) / (W * 0.09)) ** 2)[None, :] * 70
            img = Image.fromarray(band.astype(np.uint8)).rotate(-18, resample=Image.BILINEAR)
            self._sweep = img.convert("RGB")
        off = int(-W * 1.2 + p * W * 1.6)
        layer = self._sweep.crop((W - off, 0, W - off + W, H)) if 0 <= W - off <= W else None
        if layer is None:
            return frame
        return ImageChops.screen(frame, layer)

    @staticmethod
    def _grade(frame: Image.Image, grade: str) -> Image.Image:
        if grade == "problem":
            g = ImageOps.grayscale(frame).convert("RGB")
            frame = Image.blend(frame, g, 0.65)
            return Image.eval(frame, lambda v: int(v * 0.62))
        return frame

    def _label(self, text: str) -> Image.Image:
        if text not in self._label_cache:
            f = _font(self.captions.font_path, int(W * 0.03))
            d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
            tw = int(d.textlength(text, font=f))
            pad = int(W * 0.012)
            img = Image.new("RGBA", (tw + pad * 2, int(W * 0.03) + pad * 2), (0, 0, 0, 0))
            dd = ImageDraw.Draw(img)
            dd.rounded_rectangle([0, 0, img.width - 1, img.height - 1], pad, fill=(0, 0, 0, 140))
            dd.text((pad, pad), text, font=f, fill=(255, 255, 255, 230))
            self._label_cache[text] = img
        return self._label_cache[text]

    def frame(self, shot: Shot, t: float, index: int) -> Image.Image:
        """shot 시작 기준 t 초의 프레임."""
        p = min(max(t / shot.duration, 0), 1)
        z0, z1 = shot.zoom
        punch = 0.0
        for pt in shot.punch_at:   # 펀치 줌: 0.08초 만에 확 들어갔다가 0.4초 동안 풀림
            dt = t - pt
            if 0 <= dt < 0.5:
                env = ease_out(dt / 0.08) if dt < 0.08 else 1 - ease((dt - 0.08) / 0.42)
                punch = max(punch, 0.12 * env)
        kind = shot.shot
        if kind == "video_clip":
            frame = self._clip_frame(shot, t)
            if punch:
                frame = self._crop(frame, 1.0 + punch, 0.5, 0.5)
        elif kind in ("macro",):
            plate = macro_plate(self.cache, shot.source, shot.focus)
            scale = z0 + (z1 - z0) * ease(p) + punch
            cx = 0.5 + shot.pan[0] * 0.06 * (p - 0.5)
            cy = 0.5 + shot.pan[1] * 0.06 * (p - 0.5)
            frame = self._crop(plate, scale, cx, cy)
        elif kind == "detail_pan":
            plate = pan_plate(self.cache, shot.source)
            direction = 1 if shot.pan[0] >= 0 else -1
            pp = ease(p)
            cx = 0.5 + direction * (pp - 0.5) * 0.5
            frame = self._crop(plate, 1.0 + punch, cx, 0.5)
        elif kind == "parallax":
            # 배경은 느리게, 제품은 반대 방향 + 살짝 확대 -> 입체감
            scale_p = 1.2
            bg, fg, a, (fx, fy) = _hero_parts(self.cache, shot.source, scale_p, 0.98, 0.6)
            d = 1 if shot.pan[0] >= 0 else -1
            bg_scale = 1.0 + 0.04 * ease(p)
            cx = 0.5 + d * 0.04 * (p - 0.5)
            frame = self._crop(bg, bg_scale, cx, 0.5)
            pw, ph = bg.size
            base = min(pw / W, ph / H)
            bw = W * base / bg_scale
            k = W / bw
            x0 = cx * pw - bw / 2
            y0 = 0.5 * ph - (H * base / bg_scale) / 2
            fs = k * (1.12 + 0.1 * ease(p) + punch)
            fw, fh = int(fg.width * fs), int(fg.height * fs)
            cxp = (fx + fg.width / 2 - x0) * k - d * W * 0.08 * (p - 0.5)
            cyp = (fy + fg.height / 2 - y0) * k
            px, py = int(cxp - fw / 2), int(cyp - fh / 2)
            a2 = a.resize((fw, fh), Image.BILINEAR)
            frame = frame.copy()
            _with_shadow(frame, a2, (px, py), int(W * 0.025), (int(W * 0.012), int(H * 0.018)))
            frame.paste(fg.resize((fw, fh), Image.BILINEAR), (px, py), a2)
        else:
            # hero 계열
            fg_ratio = 0.84 if kind in ("cta_card",) else 0.8
            plate = hero_plate(self.cache, shot.source, fg_ratio=fg_ratio)
            if kind == "punch_in":
                scale = 1.0 + 0.1 * ease_out(min(t / 0.35, 1)) + 0.03 * p + punch
            elif kind == "whip_reveal":
                scale = 1.05 + 0.05 * ease(p) + punch
            elif kind == "cta_card":
                scale = 1.08 - 0.06 * ease_out(p) + punch
            elif kind == "problem_card":
                scale = 1.0 + 0.1 * ease(p)
            else:
                scale = z0 + (z1 - z0) * ease(p) + punch
            cx = 0.5 + shot.pan[0] * 0.05 * (ease(p) - 0.5)
            cy = 0.5 + shot.pan[1] * 0.04 * (ease(p) - 0.5)
            frame = self._crop(plate, scale, cx, cy)
            if kind == "rack_focus" and t < 0.7:
                frame = frame.filter(ImageFilter.GaussianBlur(14 * (1 - ease(t / 0.7))))
            if kind in ("light_sweep", "cta_card") or (kind == "hero_push" and index % 2 == 0):
                frame = self._light_sweep(frame, ease(p))
            if kind == "problem_card":
                frame = frame.filter(ImageFilter.GaussianBlur(26))

        frame = self._grade(frame, shot.grade)

        # 전환 효과 (shot 시작 부분)
        if shot.transition_in == "whip" and t < 0.2:
            k = 1 - ease_out(t / 0.2)
            arr = np.asarray(frame).astype(np.float32)
            shift = int(W * 0.5 * k)
            acc = np.zeros_like(arr)
            n = 6
            for i in range(n):
                acc += np.roll(arr, shift * i // n, axis=1)
            frame = Image.fromarray((acc / n).astype(np.uint8))
        elif shot.transition_in == "flash" and t < 2 / self.fps:
            frame = Image.blend(frame, Image.new("RGB", frame.size, (255, 255, 255)), 0.7)

        # 자막
        if shot.caption_words:
            visible = sum(1 for w in shot.caption_words if w.start <= t)
            if visible:
                last = shot.caption_words[visible - 1]
                pop = (t - last.start) / brain.system("caption_rules")["pop_seconds"]
                res = self.captions.render(id(shot), shot.caption_words, visible, pop, shot.caption_zone)
                if res:
                    layer, pos = res
                    frame = frame.copy()
                    frame.paste(layer, pos, layer)
        if shot.label:
            lab = self._label(shot.label)
            frame = frame.copy() if not shot.caption_words else frame
            frame.paste(lab, (int(W * self.safe["left"]), int(H * 0.06)), lab)
        return frame

    # ------------------------------------------------------------------ encode
    def render(self, shots: list[Shot], out: Path, crf: int = 18, preset: str = "medium",
               progress_cb=None) -> Path:
        """영상 트랙만 인코딩 (오디오는 mux 단계에서)."""
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(self.fps), "-i", "-", "-an",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-g", str(self.fps * 2), "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        total = sum(round(s.duration * self.fps) for s in shots)
        done = 0
        try:
            for i, shot in enumerate(shots):
                n = round(shot.duration * self.fps)
                for f in range(n):
                    proc.stdin.write(self.frame(shot, f / self.fps * shot.speed, i).tobytes())
                    done += 1
                    if progress_cb and done % self.fps == 0:
                        progress_cb(done / total)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        self.close_clips()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg 인코딩 실패: {err[-500:]}")
        return out
