"""MOTION GRAPHIC: 모션그래픽 21가지 기법을 장면별로 겹쳐 쓰는 상품 모션그래픽 영상 (Python/Pillow/numpy → ffmpeg, 기존 렌더러와 같은 방식).

구성 (120 BPM, 1박 = 0.5초, 장면/전환/큰 움직임은 모두 박자 위에서 시작)
 S1 오프닝 0~3s   푸시 인 + 키네틱 타이포 + 비트 싱크 (스태거/오버랩/팔로스루/아크/패럴랙스)
 T1 3s            매치컷 (링 모양이 컷을 넘어 이어짐) → S2 가 마스크 리빌로 시작
 S2 제품 등장      마스크 리빌 → 예비동작 → 스쿼시 앤 스트레치(아크로 튀어오름) → 홀드, 그림자/반짝임(세컨더리 액션)
 T2 6s            휩 팬 (모션 블러)
 S3 특징           스태거 + 오버랩 + 팔로스루(글자가 늦게 따라옴), 아이콘 상하 흔들림(세컨더리), 패럴랙스
 T3 9s            줌 스루 (모션 블러)
 S4 숫자           카운트업 (이징 아웃) + 푸시 인 + 홀드 + 키네틱 타이포
 T4 12s           아이리스
 S5 이동           제품이 아크 경로로 이동 + 모션 블러 + 팔로스루(회전이 늦게 따라옴) + 강한 패럴랙스
 T5 15s           매치컷 (제품 위치/크기/각도가 컷을 넘어 일치)
 S6 엔딩/루프      키네틱 CTA + 홀드 + 예비동작으로 퇴장 → 처음 상태로 돌아가 루프

규칙
- 모든 움직임은 tween()/track() 으로만 계산 → 반드시 이징을 거친다 (선형 보간 함수 없음).
- 기법은 '선언'이 아니라 실제로 그 코드 경로가 실행될 때 rec.use() 로 기록 → 장면별 표는 실제 사용 기록에서 만든다.
- 입력에 없는 가격/할인/후기/성능 수치는 만들지 않는다. 가격/할인은 사용자가 준 값만, 없으면 '핵심 특징 개수'(입력한 특징의 실제 개수)를 센다.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..video import ffmpeg_exe
from . import audio as audio_mod
from .motion import caption_font_path

W, H, FPS = 540, 960, 30
BPM = 120
BEAT = 60.0 / BPM                      # 0.5 s


def B(n: float) -> float:
    """박(beat) → 초. 모든 장면 시작/전환/큰 움직임은 이 함수로 박자 위에 놓는다."""
    return n * BEAT


SCENE_BEATS = 6                        # 장면 하나 = 6박 = 3초
SCENES = ["S1", "S2", "S3", "S4", "S5", "S6"]
TOTAL = B(SCENE_BEATS * len(SCENES))   # 18 s

TECHNIQUES = [("ease", "이징"), ("anticipation", "예비동작"), ("squash_stretch", "스쿼시 앤 스트레치"), ("arc", "아크"), ("follow_through", "팔로스루"),
              ("overlap", "오버랩"), ("stagger", "스태거"), ("match_cut", "매치컷"), ("parallax", "패럴랙스"), ("mask_reveal", "마스크 리빌"),
              ("motion_blur", "모션 블러"), ("hold", "홀드"), ("secondary_action", "세컨더리 액션"), ("zoom_through", "줌 스루"), ("whip_pan", "휩 팬"),
              ("iris", "아이리스"), ("kinetic_type", "키네틱 타이포"), ("count_up", "카운트업"), ("push_in", "푸시 인"), ("beat_sync", "비트 싱크"), ("loop", "루프")]
TECH_KO = dict(TECHNIQUES)


# ------------------------------------------------------------------ 기록 (실제 실행된 기법만)
class Rec:
    def __init__(self) -> None:
        self.used: dict[str, set[str]] = {}
        self.cur = "-"
        self.ease_calls = 0

    def scene(self, name: str) -> None:
        self.cur = name
        self.used.setdefault(name, set())

    def use(self, *techs: str) -> None:
        self.used.setdefault(self.cur, set()).update(techs)


rec = Rec()

# ------------------------------------------------------------------ 이징 (모든 움직임은 여기를 거친다)
_C1 = 1.70158
_C3 = _C1 + 1


def _clamp(t: float) -> float:
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def _elastic(t: float) -> float:
    if t in (0.0, 1.0):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


EASES = {
    "in_out_cubic": lambda t: 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2,
    "in_out_quint": lambda t: 16 * t ** 5 if t < 0.5 else 1 - (-2 * t + 2) ** 5 / 2,
    "out_cubic": lambda t: 1 - (1 - t) ** 3,
    "in_cubic": lambda t: t ** 3,
    "out_back": lambda t: 1 + _C3 * (t - 1) ** 3 + _C1 * (t - 1) ** 2,          # 목표를 살짝 지나쳤다가 돌아옴 (팔로스루)
    "in_back": lambda t: _C3 * t ** 3 - _C1 * t ** 2,                           # 반대 방향으로 먼저 움찔 (예비동작)
    "out_expo": lambda t: 1.0 if t >= 1 else 1 - 2 ** (-10 * t),
    "out_elastic": _elastic,
}


def E(name: str, t: float) -> float:
    rec.ease_calls += 1
    rec.use("ease")                                   # 이징을 실제로 계산한 장면에 자동 기록
    return EASES[name](_clamp(t))


def tween(a: float, b: float, t: float, ease: str) -> float:
    return a + (b - a) * E(ease, t)


def seg(t: float, t0: float, dur: float) -> float:
    return _clamp((t - t0) / dur) if dur > 0 else (1.0 if t >= t0 else 0.0)


def track(t: float, keys: list[tuple[float, float, str]]) -> float:
    """키프레임 (시간, 값, 이전 키에서 이 키까지의 이징). 앞/뒤는 처음/마지막 값을 유지(홀드)."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0, _), (t1, v1, ez) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * E(ez, (t - t0) / (t1 - t0))
    return keys[-1][1]


def pulse(t: float) -> float:
    """박자마다 1 → 0 으로 빠지는 펄스 (박 앞뒤 대칭이라 루프 경계에서도 이어진다)."""
    d = ((t + BEAT / 2) % BEAT) - BEAT / 2
    return math.exp(-((d / 0.09) ** 2))


def bez(a: tuple[float, float], c: tuple[float, float], b: tuple[float, float], p: float) -> tuple[float, float]:
    """2차 베지어 = 직선이 아닌 '아크' 경로."""
    q = 1 - p
    return (q * q * a[0] + 2 * q * p * c[0] + p * p * b[0], q * q * a[1] + 2 * q * p * c[1] + p * p * b[1])


# ------------------------------------------------------------------ 스프라이트
_FONT: dict[int, ImageFont.ImageFont] = {}


def font(size: int):
    if size not in _FONT:
        fp = caption_font_path(None)
        _FONT[size] = ImageFont.truetype(fp, size) if fp else ImageFont.load_default(size=size)
    return _FONT[size]


_TEXT: dict[tuple, Image.Image] = {}


def text_img(text: str, size: int, fill=(255, 255, 255, 255), stroke: int = 0) -> Image.Image:
    key = (text, size, fill, stroke)
    if key not in _TEXT:
        f = font(size)
        d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        l, t, r, b = d.textbbox((0, 0), text, font=f, stroke_width=stroke)
        im = Image.new("RGBA", (r - l + 8 + stroke * 2, b - t + 8 + stroke * 2), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4 + stroke - l, 4 + stroke - t), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 160))
        _TEXT[key] = im
    return _TEXT[key]


def place(base: Image.Image, sp: Image.Image, cx: float, cy: float, sx: float = 1.0, sy: float | None = None, rot: float = 0.0, alpha: float = 1.0) -> None:
    """RGBA 스프라이트를 중심 (cx, cy) 에 배치. sx/sy 로 늘이고 찌그러뜨리고 rot(도) 로 회전."""
    sy = sx if sy is None else sy
    if alpha <= 0.01 or sx <= 0.01 or sy <= 0.01:
        return
    w, h = max(1, int(sp.width * sx)), max(1, int(sp.height * sy))
    im = sp.resize((w, h), Image.BILINEAR) if (w, h) != sp.size else sp
    if abs(rot) > 0.05:
        im = im.rotate(rot, resample=Image.BILINEAR, expand=True)
    if alpha < 0.99:
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im = im.copy()
        im.putalpha(a)
    x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(base.width, x + im.width), min(base.height, y + im.height)
    if x1 <= x0 or y1 <= y0:
        return
    base.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def star(size: int, color) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, r, k = size / 2, size / 2 - 1, size * 0.12
    d.polygon([(c, c - r), (c + k, c - k), (c + r, c), (c + k, c + k), (c, c + r), (c - k, c + k), (c - r, c), (c - k, c - k)], fill=color)
    return im


# ------------------------------------------------------------------ 장면 컨텍스트 (상품 데이터/에셋)
class Ctx:
    def __init__(self, photo: str, name: str, features: list[str], price: int | None, discount: int | None, cta: str):
        from .product import cutout
        self.name = name.strip() or "상품"
        self.features = [f.strip() for f in features if f.strip()][:3]
        self.price, self.discount = price, discount
        self.cta = cta
        img = Image.open(photo).convert("RGB")
        cut = cutout(img)
        if cut is not None:                                       # 신뢰할 수 있는 배경 제거만 사용 (상품 모양을 바꾸지 않음)
            bb = cut.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
            cut = cut.crop(bb) if bb else cut
            self.product = cut
            arr = np.asarray(cut)
            m = arr[..., 3] > 200
            col = arr[m][:, :3].mean(axis=0) if m.any() else np.array([60, 140, 130])
        else:
            card = img.copy()
            card.thumbnail((420, 420))
            msk = Image.new("L", card.size, 0)
            ImageDraw.Draw(msk).rounded_rectangle([0, 0, card.width - 1, card.height - 1], 28, fill=255)
            self.product = card.convert("RGBA")
            self.product.putalpha(msk)
            col = np.asarray(card).reshape(-1, 3).mean(axis=0)
        hi = np.array(col, dtype=float)
        hi = hi + (hi - hi.mean()) * 0.6                          # 채도 살짝 올려 포인트 컬러
        self.accent = tuple(int(max(40, min(255, v * 1.15 + 30))) for v in hi)
        self.accent_dark = tuple(int(v * 0.16) for v in self.accent)
        s = 520 / self.product.height
        self.product = self.product.resize((max(1, int(self.product.width * s)), 520), Image.LANCZOS)
        self.bg_base = self._gradient()
        self.layers = [self._bokeh(seed, n, rmin, rmax, a) for seed, n, rmin, rmax, a in ((1, 14, 40, 90, 30), (2, 12, 22, 50, 45), (3, 10, 8, 26, 70))]
        self.name_lines = self._wrap(self.name)

    def _gradient(self) -> Image.Image:
        top = np.array((10, 12, 22), dtype=np.float32)
        bot = np.array(self.accent_dark, dtype=np.float32) * 0.9 + np.array((8, 10, 16), dtype=np.float32)
        t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        arr = top * (1 - t) + bot * t
        return Image.fromarray(np.repeat(arr, W, axis=1).astype(np.uint8)).convert("RGBA")

    def _bokeh(self, seed: int, n: int, rmin: int, rmax: int, alpha: int) -> Image.Image:
        rng = np.random.default_rng(seed)
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for _ in range(n):
            r = int(rng.integers(rmin, rmax))
            x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
            c = tuple(int(v * 0.8 + 40) for v in self.accent)
            for dx in (-W, 0, W):                                   # 가로로 이어 붙여도 끊기지 않게
                d.ellipse([x + dx - r, y - r, x + dx + r, y + r], fill=c + (alpha,))
        return im.filter(ImageFilter.GaussianBlur(2 if rmax < 30 else 6))

    @staticmethod
    def _wrap(name: str) -> list[str]:
        words = name.split()
        lines, cur = [], ""
        for w in words:
            if cur and len(cur) + len(w) + 1 > 8 and len(lines) < 1:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        return lines[:2]


# ------------------------------------------------------------------ 카메라/배경 (패럴랙스)
CAM_KEYS = [(0.0, 0.0, "in_out_cubic"), (B(6), 120.0, "in_out_cubic"), (B(12), 260.0, "in_out_cubic"), (B(18), 380.0, "in_out_cubic"),
            (B(24), 520.0, "in_out_cubic"), (B(30), 1500.0, "in_out_quint"), (B(33), 1500.0, "in_out_cubic"), (TOTAL, 0.0, "in_out_cubic")]
RING_IDLE = 150.0
RING_MATCH = 230.0
PUSH_END = 1.18                          # S1 푸시 인 끝 배율 → 컷 직전 링은 이만큼 커 보인다 (매치컷 반지름 = RING_MATCH * PUSH_END)
MATCH_R = RING_MATCH * PUSH_END


def cam_x(t: float) -> float:
    return track(t, CAM_KEYS)


def bg(c: Ctx, t: float, extra_cam: float = 0.0) -> Image.Image:
    """그라디언트 + 깊이가 다른 3겹 보케. 카메라가 움직이면 멀수록 느리게(패럴랙스)."""
    rec.use("parallax")
    im = c.bg_base.copy()
    cx = cam_x(t) + extra_cam
    for layer, k in zip(c.layers, (0.12, 0.38, 0.9)):
        off = int(cx * k) % W
        im.alpha_composite(layer, (-off, 0))
        im.alpha_composite(layer, (W - off, 0))
    return im


def ring(im: Image.Image, cx: float, cy: float, r: float, color, width: int = 7, alpha: int = 255) -> None:
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse([cx - r, cy - r, cx + r, cy + r], outline=color + (alpha,), width=width)
    im.alpha_composite(ov)


def push(im: Image.Image, s: float, cx: float = W / 2, cy: float = H / 2) -> Image.Image:
    """푸시 인: 화면 전체를 (cx,cy) 중심으로 s 배 확대."""
    rec.use("push_in")
    if s <= 1.001:
        return im
    w, h = W / s, H / s
    x0 = min(max(0, cx - w / 2), W - w)
    y0 = min(max(0, cy - h / 2), H - h)
    return im.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))


def kinetic_line(im: Image.Image, text: str, size: int, cx: float, cy: float, t: float, t0: float, color, *, stagger: float = 0.05, dur: float = 0.55,
                 origin: tuple[float, float] = (W * 0.85, H * 1.05), lift: float = 260.0, out_at: float | None = None, exit_dur: float = 0.4) -> None:
    """키네틱 타이포: 글자마다 스태거 지연 + 서로 겹치는 지속시간(오버랩) + out_back 오버슈트(팔로스루) + 베지어 아크 경로 + 회전/스케일 팝.
    out_at 이 있으면 그 시각부터 반대로(in_back 예비동작 → 화면 밖) 퇴장."""
    rec.use("kinetic_type", "stagger", "overlap", "follow_through", "arc")
    sps = [text_img(ch, size, color) if ch.strip() else None for ch in text]
    widths = [sp.width - 8 if sp else int(size * 0.35) for sp in sps]
    if sum(widths) > W * 0.88:                                               # 화면 폭을 넘으면 글자 크기를 줄여 맞춘다 (잘림 방지)
        size = max(24, int(size * W * 0.88 / sum(widths)))
        sps = [text_img(ch, size, color) if ch.strip() else None for ch in text]
        widths = [sp.width - 8 if sp else int(size * 0.35) for sp in sps]
    total_w = sum(widths)
    x = cx - total_w / 2
    for i, (ch, sp) in enumerate(zip(text, sps)):
        gx = x + widths[i] / 2
        x += widths[i]
        if sp is None:
            continue
        ti = t0 + i * stagger
        p = seg(t, ti, dur)
        pe = E("out_back", p)
        ctrl = ((origin[0] + gx) / 2, cy + lift)
        px, py = bez((origin[0], origin[1]), ctrl, (gx, cy), pe)
        rot = (1 - pe) * 35 * (1 if i % 2 == 0 else -1)
        sc = 0.4 + 0.6 * pe
        a = E("out_cubic", seg(t, ti, 0.18))
        if out_at is not None:
            q = seg(t, out_at + i * stagger * 0.6, exit_dur)
            if q > 0:
                qe = E("in_back", q)                                   # 살짝 뒤로 움찔했다가 날아감
                px, py = bez((gx, cy), (gx - 90, cy - 180), (-120, -60), qe)
                a *= 1 - E("out_cubic", seg(q, 0.6, 0.4))
                sc *= 1 - 0.4 * qe
        place(im, sp, px, py, sc, sc, rot, a)


# ------------------------------------------------------------------ 장면
def product_center_pose() -> tuple[float, float, float, float]:
    """T5 매치컷이 두 장면에서 똑같이 쓰는 제품 위치/크기/각도 (x, y, scale, rot)."""
    return (W / 2, H * 0.50, 0.95, 0.0)


def s1_opening(c: Ctx, t: float) -> Image.Image:
    """오프닝 0~3초: 푸시 인 + 키네틱 타이포 + 비트 싱크."""
    rec.scene("S1")
    im = bg(c, t)
    pu = pulse(t)
    rec.use("beat_sync")
    r = RING_IDLE + 10 * pu + tween(0, RING_MATCH - RING_IDLE, seg(t, B(4), B(2)), "in_cubic")     # 마지막 2박 동안 링이 매치컷 크기로 커짐
    ring(im, W / 2, H * 0.45, r, c.accent, 7)
    rec.use("secondary_action")                                              # 링 두께/바 강조는 주 동작을 받쳐 주는 작은 움직임
    y0 = H * 0.40
    sizes = [96, 84]
    for li, line in enumerate(c.name_lines):
        s = sizes[min(li, 1)]
        kinetic_line(im, line, s, W / 2, y0 + li * (s + 18), t, B(0) + li * B(1) * 0.5, (255, 255, 255, 255), stagger=0.05, dur=0.6)
    bar = tween(0, 220, seg(t, B(2), B(1)), "out_expo")
    d = ImageDraw.Draw(im)
    by = y0 + len(c.name_lines) * 110 + 20
    d.rounded_rectangle([W / 2 - bar / 2, by, W / 2 + bar / 2, by + 8 + 6 * pu], 4, fill=c.accent + (255,))
    s_push = tween(1.0, PUSH_END, seg(t, 0, B(6)), "in_out_cubic")
    return push(im, s_push, W / 2, H * 0.45).convert("RGB")


def _pose_product(c: Ctx, im: Image.Image, x: float, y: float, sx: float, sy: float, rot: float = 0.0, alpha: float = 1.0, base: float = 0.95) -> None:
    place(im, c.product, x, y, base * sx, base * sy, rot, alpha)


def s2_product(c: Ctx, t: float) -> Image.Image:
    """제품 등장: 마스크 리빌 → 예비동작 → 스쿼시 앤 스트레치 → 홀드."""
    rec.scene("S2")
    base = bg(c, t + B(6))
    stage = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, cy = W / 2, H * 0.50
    # 밝은 스튜디오 원판 (마스크로 드러남)
    lit = Image.new("RGBA", (W, H), tuple(int(v * 0.35 + 18) for v in c.accent) + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx - 260, cy - 80, cx + 260, cy + 440], fill=tuple(min(255, int(v * 0.8 + 40)) for v in c.accent) + (70,))
    lit.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40)))
    # 마스크 리빌: 링이 있던 크기(RING_MATCH)에서 시작해 화면 전체로 퍼짐 (T1 매치컷과 이어짐)
    rec.use("mask_reveal", "match_cut")
    rad = tween(MATCH_R, 760, seg(t, 0, B(2)), "out_cubic")
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([cx - rad, H * 0.45 - rad, cx + rad, H * 0.45 + rad], fill=255)
    rest_y = H * 0.50
    # 제품은 처음부터 무대 위에 있고 마스크가 그 위를 열어 보여준다 → 예비동작(웅크림) → 튀어 오름(스트레치, 아크) → 착지(스쿼시) → 오버슈트 안정(팔로스루) → 홀드
    rec.use("anticipation", "squash_stretch", "arc", "hold", "follow_through", "ease")
    y = track(t, [(0.0, rest_y, "out_cubic"), (B(1), rest_y, "out_cubic"), (B(2), rest_y + 44, "in_out_cubic"), (B(3), rest_y - 150, "out_cubic"),
                  (B(4), rest_y, "in_cubic"), (B(5), rest_y, "out_elastic")])
    x = cx + track(t, [(0.0, 0, "out_cubic"), (B(2), 0, "out_cubic"), (B(3), 46, "out_cubic"), (B(4), 0, "in_out_cubic")])           # 위로 올라가며 옆으로 휘는 아크
    sy = track(t, [(0.0, 1.0, "out_cubic"), (B(1), 1.0, "out_cubic"), (B(2), 0.84, "in_out_cubic"), (B(3), 1.20, "out_cubic"), (B(4), 0.88, "in_cubic"), (B(5), 1.0, "out_elastic")])
    sx = track(t, [(0.0, 1.0, "out_cubic"), (B(1), 1.0, "out_cubic"), (B(2), 1.12, "in_out_cubic"), (B(3), 0.86, "out_cubic"), (B(4), 1.10, "in_cubic"), (B(5), 1.0, "out_elastic")])
    height_k = (rest_y - y) / 150.0                                            # 높이에 따라 그림자가 작아지고 옅어짐 (세컨더리 액션)
    rec.use("secondary_action", "beat_sync")
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sw = 230 * (1 - 0.35 * max(0, height_k))
    ImageDraw.Draw(sh).ellipse([x - sw / 2, rest_y + 270, x + sw / 2, rest_y + 300], fill=(0, 0, 0, int(120 * (1 - 0.5 * max(0, height_k)))))
    lit.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
    _pose_product(c, lit, x, y, sx, sy, 0.0, 1.0)
    st = star(30, (255, 255, 255, 255))                                         # 착지 순간 반짝임 스태거
    for i in range(8):
        ang = i * math.tau / 8
        q = seg(t, B(4) + i * 0.03, 0.5)
        if 0 < q < 1:
            rr = 120 + 150 * E("out_cubic", q)
            place(lit, st, x + math.cos(ang) * rr, rest_y + 40 + math.sin(ang) * rr * 0.8, 1 - 0.7 * q, 1 - 0.7 * q, ang * 57, 1 - q)
    base.paste(lit, (0, 0), mask)
    ring(base, cx, H * 0.45, rad, c.accent, int(7 * PUSH_END), int(255 * (1 - seg(t, B(1), B(1)))))
    return base.convert("RGB")


FEAT_ICON = ["check", "bolt", "heart"]


def icon(c: Ctx, kind: str, size: int = 70) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([2, 2, size - 3, size - 3], fill=c.accent + (255,))
    s = size / 70
    if kind == "check":
        d.line([(20 * s, 36 * s), (31 * s, 47 * s), (51 * s, 24 * s)], fill=(255, 255, 255, 255), width=int(8 * s), joint="curve")
    elif kind == "bolt":
        d.polygon([(40 * s, 14 * s), (22 * s, 40 * s), (35 * s, 40 * s), (30 * s, 58 * s), (50 * s, 30 * s), (37 * s, 30 * s)], fill=(255, 255, 255, 255))
    else:
        d.polygon([(35 * s, 54 * s), (16 * s, 34 * s), (20 * s, 22 * s), (30 * s, 20 * s), (35 * s, 28 * s), (40 * s, 20 * s), (50 * s, 22 * s), (54 * s, 34 * s)], fill=(255, 255, 255, 255))
    return im


def s3_features(c: Ctx, t: float) -> Image.Image:
    """텍스트·아이콘: 스태거로 차례로 등장, 오버랩 + 팔로스루(글자가 늦게 따라옴), 아이콘은 계속 작게 움직임."""
    rec.scene("S3")
    im = bg(c, t + B(12))
    rec.use("beat_sync", "ease")
    pu = pulse(t)
    _pose_product(c, im, W / 2, H * 0.17 + 5 * math.sin(t * 3.0), 1.0, 1.0, 0.0, 1.0, base=0.34)       # 작은 제품은 계속 둥실 (세컨더리)
    rec.use("secondary_action")
    feats = c.features or ["핵심 특징"]
    for i, ft in enumerate(feats):
        t_i = B(1) + i * B(1)                                                  # 박마다 하나씩 (스태거)
        y = H * 0.38 + i * 150
        # 칩 배경(가장 먼저) → 아이콘(조금 뒤) → 글자(더 늦게) : 서로 겹치며 끝이 늦게 따라옴 (오버랩 + 팔로스루)
        rec.use("stagger", "overlap", "follow_through", "anticipation", "arc")
        p_bg = seg(t, t_i, 0.5)
        p_ic = seg(t, t_i + 0.08, 0.55)
        p_tx = seg(t, t_i + 0.20, 0.6)
        if p_bg > 0:
            # 예비동작: 들어오기 직전 시작점 쪽으로 살짝 뒤로 물러났다가(u<0) 튀어 들어온다 (out_back 으로 목표를 지나쳤다 돌아옴)
            u = track(t, [(t_i - 0.22, 0.0, "out_cubic"), (t_i - 0.04, -0.09, "in_out_cubic"), (t_i + 0.5, 1.0, "out_back")])
            ox, oy = bez((W + 140, y + 90), (W * 0.8, y - 120), (W / 2, y), u)
            cap = Image.new("RGBA", (460, 108), (0, 0, 0, 0))
            ImageDraw.Draw(cap).rounded_rectangle([0, 0, 459, 107], 54, fill=(255, 255, 255, 34), outline=c.accent + (140,), width=2)
            place(im, cap, ox, oy, 1.0, 1.0, 0, E("out_cubic", seg(t, t_i, 0.2)))
        if p_ic > 0:
            ax = tween(W + 100, 78 + 10 * 0, p_ic, "out_back")
            ay = y + 4 * math.sin(t * 4 + i)                                   # 도착한 뒤에도 위아래로 흔들림 (세컨더리)
            sc = 1.0 + 0.08 * pu * seg(t, t_i + 0.6, 0.1)
            place(im, icon(c, FEAT_ICON[i % 3]), ax, ay, sc, sc, (1 - E("out_cubic", p_ic)) * -90, E("out_cubic", seg(t, t_i + 0.08, 0.15)))
        if p_tx > 0:
            sp = text_img(ft, 40, (255, 255, 255, 255))
            fit = min(1.0, 300.0 / sp.width)                                   # 칩 안에 들어가도록 줄임
            tx = tween(W * 0.78, 128 + sp.width * fit / 2, p_tx, "out_back")
            place(im, sp, tx, y, fit, fit, 0, E("out_cubic", seg(t, t_i + 0.2, 0.2)))
    return im.convert("RGB")


def fmt_count(v: float, kind: str) -> str:
    n = int(round(v))
    return f"{n:,}원" if kind == "price" else (f"{n}%" if kind == "pct" else f"{n}가지")


def s4_numbers(c: Ctx, t: float) -> Image.Image:
    """숫자·가격·할인율: 카운트업 (이징 아웃 → 마지막에 천천히 멈춤), 푸시 인 + 홀드."""
    rec.scene("S4")
    im = bg(c, t + B(18))
    rec.use("beat_sync", "ease")
    if c.price or c.discount:
        items = [(c.price, "price", "가격"), (c.discount, "pct", "할인")]
        tag = "예시 입력값"
    else:
        items = [(len(c.features), "count", "핵심 특징")]
        tag = "입력한 특징 수"
    items = [it for it in items if it[0]]
    rec.use("count_up", "kinetic_type", "hold", "overlap")
    n = len(items)
    for i, (val, kind, label) in enumerate(items):
        y = H * (0.5 if n == 1 else 0.33 + 0.30 * i)
        t_i = B(1) + i * B(1)
        v = val * E("out_expo", seg(t, t_i, 1.4))                                # 빠르게 올라가다 목표에서 부드럽게 멈춤
        done = seg(t, t_i + 1.4, 0.4)
        size = 110 if kind == "price" else (110 if n > 1 else 150)
        txt = fmt_count(v, kind)
        sp = text_img(txt, size, (255, 255, 255, 255), stroke=2)
        sq = 1.0 + 0.10 * E("out_back", seg(t, t_i + 1.4, 0.35)) * (1 - done) - 0.0   # 멈추는 순간 살짝 튐
        a = E("out_cubic", seg(t, t_i - 0.1, 0.25))
        place(im, sp, W / 2, y, sq, sq, 0, a)
        lab = text_img(label, 38, c.accent + (255,))
        place(im, lab, W / 2, y - size * 0.78, 1.0, 1.0, 0, a)
        if kind in ("pct", "count"):
            frac = val / 100 if kind == "pct" else min(1.0, val / 3)          # 할인율은 100% 기준, 특징 수는 3개 기준 원호
            ang = 360.0 * min(frac, 0.999) * E("out_expo", seg(t, t_i, 1.4))
            rr = 150 if n > 1 else 210
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(ov).arc([W / 2 - rr, y - rr, W / 2 + rr, y + rr], -90, -90 + ang, fill=c.accent + (255,), width=10)
            im.alpha_composite(ov)
    tg = text_img(tag, 30, (255, 255, 255, 220))
    chip = Image.new("RGBA", (tg.width + 36, 52), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle([0, 0, chip.width - 1, 51], 26, fill=(255, 255, 255, 40), outline=(255, 255, 255, 120), width=2)
    place(im, chip, W / 2, H * 0.86, 1.0, 1.0, 0, 1.0)
    place(im, tg, W / 2, H * 0.86, 1.0, 1.0, 0, 1.0)
    s_push = tween(1.0, 1.08, seg(t, 0, B(6)), "in_out_cubic")
    return push(im, s_push).convert("RGB")


ARC_A = (-120.0, H * 0.82)
ARC_C = (W * 0.35, H * 0.05)
ARC_B = product_center_pose()[:2]


def s5_arc(c: Ctx, t: float, blur_n: int = 5) -> Image.Image:
    """이동 경로: 제품이 직선이 아닌 아크로 날아와 중앙에 안착. 속도가 빠를 때 모션 블러, 회전은 늦게 따라옴(팔로스루), 배경은 크게 패럴랙스."""
    rec.scene("S5")
    t_a, t_b = B(1), B(4)
    p_now = seg(t, t_a, t_b - t_a)
    speed = abs(E("in_out_quint", p_now + 0.01) - E("in_out_quint", p_now)) / 0.01 * (1 / (t_b - t_a))
    use_blur = speed > 0.9 and p_now < 1.0
    n = blur_n if use_blur else 1
    shutter = 0.075
    acc = None
    for k in range(n):
        tt = t + ((k / (n - 1)) - 0.5) * shutter if n > 1 else t
        fr = np.asarray(_s5_frame(c, tt).convert("RGB"), dtype=np.float32)
        acc = fr if acc is None else acc + fr
    if n > 1:
        rec.use("motion_blur")
    return Image.fromarray((acc / n).astype(np.uint8))


def _s5_frame(c: Ctx, t: float) -> Image.Image:
    rec.use("arc", "parallax", "ease", "beat_sync")
    t_a, t_b = B(1), B(4)
    im = bg(c, t + B(24), extra_cam=0)
    p = E("in_out_quint", seg(t, t_a, t_b - t_a))
    px, py = bez(ARC_A, ARC_C, ARC_B, p)
    p_lag = E("in_out_quint", seg(t - 0.12, t_a, t_b - t_a))                       # 회전은 0.12초 늦게 따라옴 (팔로스루)
    rec.use("follow_through")
    rot = (1 - p_lag) * -38 * (1 - 0.0)
    # 속도선 (전경 패럴랙스)
    sp_v = 1 - seg(p, 0.55, 0.45)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(9):
        yy = (i * 113 + 40) % H
        off = (t * 2600 * sp_v + i * 97) % (W + 200)
        d.line([(W - off, yy), (W - off + 120 * sp_v, yy)], fill=(255, 255, 255, int(110 * sp_v)), width=3)
    im.alpha_composite(ov)
    # 키워드 글자: 제품 아크를 따라 스태거로 뒤따라옴
    rec.use("kinetic_type", "stagger", "overlap")
    word = (c.features[0] if c.features else c.name)[:8]
    for i, ch in enumerate(word):
        if not ch.strip():
            continue
        pc = E("in_out_quint", seg(t - 0.09 * (i + 1), t_a, t_b - t_a))
        gx, gy = bez(ARC_A, ARC_C, (W / 2 - len(word) * 24 + i * 48, H * 0.2), pc)
        place(im, text_img(ch, 54, c.accent + (255,)), gx, gy, 1, 1, (1 - pc) * 20, E("out_cubic", seg(t, t_a, 0.2)) * (1 - E("out_cubic", seg(t, B(4.5), B(0.8)))))
    # 제품: 안착 직전 살짝 스쿼시 (착지 감각)
    land = seg(t, t_b, B(1) - 0.0)
    sq = 1 + 0.06 * math.sin(land * math.pi) * (1 - land)
    _pose_product(c, im, px, py, 1.0 / max(sq, 0.2), sq, rot, 1.0, base=product_center_pose()[2])
    if p >= 1.0:
        rec.use("hold")
    return im.convert("RGB")


def s6_ending(c: Ctx, t: float) -> Image.Image:
    """엔딩: 매치컷으로 이어진 제품 → CTA 키네틱 → 홀드 → 예비동작으로 퇴장 → 처음 상태(루프)."""
    rec.scene("S6")
    im = bg(c, t + B(30))
    rec.use("beat_sync", "ease")
    x, y, sc, rot = product_center_pose()
    # 천천히 푸시 인 + 홀드, 마지막 1.5박에서 예비동작(살짝 커짐) 후 작아지며 사라짐
    pre = track(t, [(0.0, 1.0, "out_cubic"), (B(4), 1.0, "out_cubic"), (B(4.5), 1.12, "in_out_cubic"), (B(5.5), 0.0, "in_back")])
    rec.use("hold", "anticipation", "loop")
    py = y + track(t, [(0.0, 0, "out_cubic"), (B(4), 0, "out_cubic"), (B(5.5), -40, "in_cubic")]) + 6 * math.sin(t * 3) * (1 - seg(t, B(4), B(1)))
    _pose_product(c, im, x, py, pre, pre, 0.0, 1.0, base=sc)
    cta = c.cta
    kinetic_line(im, cta, 46, W / 2, H * 0.80, t, B(1), (255, 255, 255, 255), stagger=0.045, dur=0.55, origin=(W * 0.1, H * 1.05), lift=-220, out_at=B(4), exit_dur=0.45)
    # 링은 처음 상태(RING_IDLE)로 돌아가 오프닝과 이어진다 (루프)
    r_hold = RING_MATCH + 40 * (1 - E("out_cubic", seg(t, 0, B(1))))
    r = tween(RING_MATCH, RING_IDLE, seg(t, B(4.5), B(1.5)), "in_out_cubic") if t >= B(4.5) else r_hold
    ring(im, W / 2, H * 0.45, r + 10 * pulse(t + B(30)), c.accent, 7, int(255 * E("out_cubic", seg(t, 0, B(1)))))
    s_push = tween(1.0, 1.06, seg(t, 0, B(4)), "in_out_cubic") * 1.0
    s_push = s_push if t < B(4) else tween(1.06, 1.0, seg(t, B(4), B(2)), "in_out_cubic")
    return push(im, s_push).convert("RGB")


DRAW = {"S1": s1_opening, "S2": s2_product, "S3": s3_features, "S4": s4_numbers, "S5": s5_arc, "S6": s6_ending}


def scene_frame(c: Ctx, idx: int, t_global: float) -> Image.Image:
    start = B(SCENE_BEATS * idx)
    return DRAW[SCENES[idx]](c, max(0.0, t_global - start) if idx else t_global)


# ------------------------------------------------------------------ 전환
def _hblur(im: Image.Image, length: float, n: int = 7) -> Image.Image:
    if length < 1.5:
        return im
    arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    acc = np.zeros_like(arr)
    for k in range(n):
        acc += np.roll(arr, int((k / (n - 1) - 0.5) * length), axis=1)
    return Image.fromarray((acc / n).astype(np.uint8))


def _radial(im: Image.Image, s0: float, s1: float, n: int = 6) -> Image.Image:
    arr = np.zeros((H, W, 3), dtype=np.float32)
    for k in range(n):
        s = s0 + (s1 - s0) * k / (n - 1)
        w, h = W / s, H / s
        crop = im.resize((W, H), Image.BILINEAR, box=((W - w) / 2, (H - h) / 2, (W + w) / 2, (H + h) / 2)) if s >= 1 else im
        arr += np.asarray(crop.convert("RGB"), dtype=np.float32)
    return Image.fromarray((arr / n).astype(np.uint8))


def trans_whip(a: Image.Image, b: Image.Image, p: float) -> Image.Image:
    """휩 팬: 옆으로 확 쓸리며 모션 블러."""
    rec.scene("T2")
    rec.use("whip_pan", "motion_blur", "ease")
    e = E("in_out_quint", p)
    off = e * W
    canvas = Image.new("RGB", (W * 2, H))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (W, 0))
    view = canvas.crop((int(off), 0, int(off) + W, H))
    speed = abs(E("in_out_quint", p + 0.02) - E("in_out_quint", p)) / 0.02
    rec.use("beat_sync")
    return _hblur(view, speed * W * 0.12)


def trans_zoom(a: Image.Image, b: Image.Image, p: float) -> Image.Image:
    """줌 스루: 앞 장면 속으로 파고들어 지나가면 다음 장면이 멀리서 다가와 자리잡음."""
    rec.scene("T3")
    rec.use("zoom_through", "motion_blur", "ease")
    rec.use("beat_sync")
    sa = tween(1.0, 5.5, p, "in_cubic")
    sb = tween(0.35, 1.0, p, "out_cubic")
    fa = _radial(a, sa * 0.9, sa * 1.08)
    small = b.resize((max(1, int(W * sb)), max(1, int(H * sb))), Image.BILINEAR)
    fb = Image.new("RGB", (W, H), (0, 0, 0))
    fb.paste(small, ((W - small.width) // 2, (H - small.height) // 2))
    if sb < 0.98:
        fb = _radial(fb, 0.97, 1.03)
    return Image.blend(fa, fb, E("in_out_cubic", seg(p, 0.45, 0.4)))


def trans_iris(a: Image.Image, b: Image.Image, p: float, accent) -> Image.Image:
    """아이리스: 원이 점으로 닫혔다가(앞 장면) 다시 열리며 다음 장면."""
    rec.scene("T4")
    rec.use("iris", "ease")
    rmax = math.hypot(W, H) / 2 + 10
    cx, cy = W / 2, H / 2
    rec.use("beat_sync")                                  # 닫히는 순간이 박 위 (경계)
    if p < 0.44:
        src, r = a, tween(rmax, 0, p / 0.44, "in_cubic")
    elif p < 0.56:
        src, r = b, 0.0                                   # 완전히 닫힌 채 잠깐 멈춤 (홀드)
        rec.use("hold")
    else:
        src, r = b, tween(0, rmax, (p - 0.56) / 0.44, "out_cubic")
    out = Image.new("RGB", (W, H), (0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    out.paste(src, (0, 0), mask)
    if r > 4:
        d = ImageDraw.Draw(out)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent, width=6)
    return out


TRANS = {1: ("match", 0.0), 2: ("whip", 0.4), 3: ("zoom", 0.5), 4: ("iris", 0.6), 5: ("match", 0.0)}


def frame_at(c: Ctx, t: float) -> Image.Image:
    """전체 타임라인의 한 프레임 (전환 구간이면 두 장면을 합성)."""
    t = min(max(t, 0.0), TOTAL - 1e-6)
    idx = min(int(t // B(SCENE_BEATS)), len(SCENES) - 1)
    for b_idx, (kind, dur) in TRANS.items():
        tb = B(SCENE_BEATS * b_idx)
        if kind == "match":
            if abs(t - tb) < 1e-9 or (idx == b_idx and t - tb < 1.0 / FPS):
                rec.scene(f"T{b_idx}")
                rec.use("match_cut", "ease", "hold", "beat_sync")          # 박 위에서 컷, 링/제품은 컷을 넘어 그대로 유지(홀드)
            continue
        lo, hi = tb - dur / 2, tb + dur / 2
        if lo <= t < hi:
            p = (t - lo) / dur
            a = scene_frame(c, b_idx - 1, t)
            b = scene_frame(c, b_idx, t)
            if kind == "whip":
                return trans_whip(a, b, p)
            if kind == "zoom":
                return trans_zoom(a, b, p)
            return trans_iris(a, b, p, c.accent)
    return scene_frame(c, idx, t)


# ------------------------------------------------------------------ 소리 (박자에 맞춘 음악 + 효과음)
def schedule() -> list[dict]:
    """큰 움직임/컷/효과음 시각 (모두 박자 격자 위: 1박 = 0.5초, 8분음표 단위)."""
    s = B(SCENE_BEATS)
    ev = [(0.0, "hit", 0.55), (B(1), "pop", 0.5), (B(2), "pop", 0.5), (B(3), "pop", 0.5),
          (s * 1, "impact", 0.55), (s * 1 + B(2), "whoosh", 0.5), (s * 1 + B(4), "hit", 0.6),
          (s * 2 - 0.5, "swipe", 0.55), (s * 2 + B(1), "pop", 0.5), (s * 2 + B(2), "pop", 0.5), (s * 2 + B(3), "pop", 0.5),
          (s * 3 - 0.5, "riser", 0.4), (s * 3, "impact", 0.6), (s * 3 + B(1), "click", 0.4), (s * 3 + B(2), "click", 0.4), (s * 3 + B(4), "ding", 0.5),
          (s * 4 - 0.5, "swipe", 0.5), (s * 4, "soft_hit", 0.6), (s * 4 + B(1), "whoosh", 0.55), (s * 4 + B(4), "hit", 0.6),
          (s * 5, "impact", 0.55), (s * 5 + B(1), "pop", 0.45), (s * 5 + B(4), "whoosh", 0.5), (TOTAL - B(0.5), "ding", 0.35)]
    return [{"t": round(t, 3), "sfx": f, "gain": g} for t, f, g in ev if t < TOTAL]


def make_audio(out: Path) -> Path:
    return audio_mod.build_mix(TOTAL, schedule(), [], out, music=True, music_style={"bpm": BPM, "kick": 0.85, "pad": 0.2, "gain": 0.45})


# ------------------------------------------------------------------ 렌더
def parse_cta(cta: str | None) -> str:
    return (cta or "자세한 정보는 링크에서").strip()[:16]


def render(photo: str, out: str | Path, *, name: str, features: list[str] | None = None, price: int | None = None, discount: int | None = None,
           cta: str | None = None, crf: int = 20, progress_cb=None) -> dict:
    """모션그래픽 MP4 생성. 반환: {video, seconds, frames, techniques(장면별 실제 사용 기록), schedule}"""
    global rec
    rec = Rec()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = Ctx(photo, name, features or [], price, discount, parse_cta(cta))
    n_frames = int(round(TOTAL * FPS))
    with tempfile.TemporaryDirectory() as td:
        vid = Path(td) / "v.mp4"
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an",
               "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(vid)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        first = last = None
        for i in range(n_frames):
            fr = frame_at(c, i / FPS)
            if i == 0:
                first = np.asarray(fr, dtype=np.int16)
            last = np.asarray(fr, dtype=np.int16) if i == n_frames - 1 else last
            proc.stdin.write(fr.convert("RGB").tobytes())
            if progress_cb and i % FPS == 0:
                progress_cb(i / n_frames)
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg 인코딩 실패: {err[-400:]}")
        wav = make_audio(Path(td) / "a.wav")
        r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(vid), "-i", str(wav), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"mux 실패: {r.stderr[-300:]}")
    loop_gap = float(np.abs(first - last).mean())            # 마지막 프레임과 첫 프레임의 평균 차이 (작을수록 루프가 자연스럽다)
    return {"video": str(out), "seconds": TOTAL, "frames": n_frames, "bpm": BPM, "loop_diff": round(loop_gap, 2), "techniques": technique_table(),
            "schedule": schedule(), "ease_calls": rec.ease_calls}


def technique_table() -> dict:
    """장면별 실제 사용 기법 (기록 기반). 키: 장면명 → 기법 한글 이름 목록."""
    order = ["S1", "T1", "S2", "T2", "S3", "T3", "S4", "T4", "S5", "T5", "S6"]
    return {k: [TECH_KO[t] for t, _ in TECHNIQUES if t in rec.used.get(k, set())] for k in order}


SCENE_TITLES = {"S1": "오프닝 (0~3초)", "T1": "전환 ① 매치컷", "S2": "제품 등장", "T2": "전환 ② 휩 팬", "S3": "텍스트·아이콘", "T3": "전환 ③ 줌 스루",
                "S4": "숫자·가격·할인율", "T4": "전환 ④ 아이리스", "S5": "이동 경로", "T5": "전환 ⑤ 매치컷", "S6": "엔딩 (루프)"}


def table_markdown(tech: dict) -> str:
    used = {t for ts in tech.values() for t in ts}
    rows = ["| 장면 | 사용한 기법 |", "|---|---|"] + [f"| {SCENE_TITLES[k]} | {', '.join(v)} |" for k, v in tech.items()]
    missing = [ko for _, ko in TECHNIQUES if ko not in used]
    rows.append("")
    rows.append(f"21개 기법 사용: {len(used)}/21" + (f" (미사용: {', '.join(missing)})" if missing else " — 전부 사용"))
    return "\n".join(rows)
