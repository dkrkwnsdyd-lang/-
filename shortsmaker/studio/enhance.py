"""PHOTO ENHANCEMENT V2.

ORIGINAL -> PHOTO QUALITY ANALYZER -> WB -> EXPOSURE/HIGHLIGHT/SHADOW -> DENOISE -> SHARPEN/DEBLUR
         -> COLOR/CONTRAST -> CONSERVATIVE UPSCALE -> BACKGROUND ROUTER -> PRODUCT FIDELITY QA -> ENHANCED

원칙: PRODUCT ACCURACY > BEAUTIFICATION
- 원본은 절대 덮어쓰지 않는다. ORIGINAL(src/) / ENHANCED(enhanced/) / DERIVED(derived/) 를 분리한다.
- 색은 만들지 않는다: 채도는 건드리지 않고, 화이트밸런스는 '중립색 픽셀'이 충분히 있을 때만 ±7% 안에서.
- 화질이 나쁜 사진(C)을 억지로 키우지 않는다. 업스케일은 최대 1.5배 (Lanczos, 디테일을 지어내지 않음).
- 보정 전후를 비교해 제품이 달라졌다면(형태/색/글자) 보정본을 폐기하고 더 안전한 보정본 -> 원본 순으로 되돌린다.
- 모든 보정은 numpy + Pillow (외부 AI 이미지 생성 없음). 이 파이프라인은 없는 디테일을 만들어내지 못한다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MAX_WORK_SIDE = 2400          # enhanced 는 영상(1080x1920)에 충분한 크기까지만 (원본은 그대로 보관)
UPSCALE_TARGET = 1080         # 짧은 변이 이보다 작으면 (C 아님) 최대 1.5배까지만 키운다
MAX_UPSCALE = 1.5
MIN_SIDE_C = 700              # 이보다 작으면 C
FIDELITY_MIN = 90             # Product Fidelity 최소 점수
EDGE_CORR_MIN = 0.90
HUE_SHIFT_MAX = 4.0           # degrees (같은 위치 픽셀의 중앙값 변화)
HUE_SHIFT_MAX_WB = 9.0        # 화이트밸런스 보정 포함 시
CHROMA_CHANGE_MAX = 0.12
CHROMA_CHANGE_MAX_WB = 0.20   # 색 틀어짐을 바로잡으면 채도도 함께 바뀐다

GRADE_TEXT = {"A": "그대로 사용 가능", "B": "보정 후 사용", "C": "품질 부족"}


# ------------------------------------------------------------------ helpers
def _load(path: str | Path) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def _gray(img: Image.Image, side: int) -> np.ndarray:
    return np.asarray(ImageOps.contain(img, (side, side), Image.LANCZOS).convert("L"), dtype=np.float32)


def _lapvar(g: np.ndarray) -> float:
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def _sobel(g: np.ndarray) -> np.ndarray:
    gx = (g[1:-1, 2:] - g[1:-1, :-2])
    gy = (g[2:, 1:-1] - g[:-2, 1:-1])
    return np.hypot(gx, gy)


def _noise_sigma(g: np.ndarray) -> float:
    """Immerkaer 잡음 추정 (평탄하지 않은 사진에서도 동작)."""
    h, w = g.shape
    if h < 8 or w < 8:
        return 0.0
    c = (g[:-2, :-2] - 2 * g[:-2, 1:-1] + g[:-2, 2:] - 2 * g[1:-1, :-2] + 4 * g[1:-1, 1:-1] - 2 * g[1:-1, 2:]
         + g[2:, :-2] - 2 * g[2:, 1:-1] + g[2:, 2:])
    return float(np.sqrt(np.pi / 2) / (6 * (w - 2) * (h - 2)) * np.abs(c).sum())


def _blockiness(g: np.ndarray) -> float:
    """8x8 블록 경계의 불연속 / 그 외 위치의 불연속. 1.0 근처가 정상, 크면 JPEG 블록 노이즈."""
    if min(g.shape) < 64:
        return 1.0
    dx = np.abs(np.diff(g, axis=1))
    cols = np.arange(dx.shape[1])
    on = dx[:, cols % 8 == 7].mean()
    off = dx[:, cols % 8 != 7].mean()
    return float(on / (off + 1e-6))


def _blur_ratio(g: np.ndarray) -> tuple[float | None, int]:
    """재블러 비율(Crete 등): 한 번 더 흐려도 구배가 거의 안 줄면 이미 흐린 것. 0 선명 ~ 1 흐림.
    질감의 양에 덜 민감해서, 매끈한 흰색 제품 + 흐린 배경(인물사진 보케)을 '흐린 사진'으로 오판하지 않는다."""
    gb = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.0)), dtype=np.float32)
    dx, dxb = np.abs(g[:, 1:] - g[:, :-1]), np.abs(gb[:, 1:] - gb[:, :-1])
    dy, dyb = np.abs(g[1:, :] - g[:-1, :]), np.abs(gb[1:, :] - gb[:-1, :])
    sx, sy = dx > 5, dy > 5
    n = int(sx.sum() + sy.sum())
    if n < 40:
        return None, n
    drop = np.maximum(0, dx - dxb)[sx].sum() + np.maximum(0, dy - dyb)[sy].sum()
    tot = dx[sx].sum() + dy[sy].sum()
    return float(1 - drop / (tot + 1e-6)), n


def focus_blur(g: np.ndarray, grid: int = 6) -> float | None:
    """가장 선명한 영역 기준 흐림 정도 (타일별 재블러 비율의 하위 20%). 배경이 흐려도 제품이 선명하면 낮게 나온다.
    기준(임시 보정, 실사진 4장 + 합성/열화 샘플 12종): 선명 ≤0.37 / 약간 흐림 0.38~0.52 / 흐림 >0.52. 표본이 적으니 사진이 쌓이면 재보정할 것."""
    g = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.MedianFilter(3)), dtype=np.float32)   # 잡음의 구배가 '선명함'으로 읽히지 않게
    h, w = g.shape
    th, tw = h // grid, w // grid
    vals = []
    for i in range(grid):
        for j in range(grid):
            r, n = _blur_ratio(g[i * th:(i + 1) * th, j * tw:(j + 1) * tw])
            if r is not None and n >= 150:
                vals.append(r)
    return float(np.percentile(vals, 20)) if vals else None


def _neutral_gains(arr: np.ndarray) -> tuple[np.ndarray, float] | None:
    """중립색(채도 낮음, 중간 밝기) 픽셀로 화이트밸런스 게인 추정. 신뢰할 수 없으면 None."""
    a = arr.reshape(-1, 3)
    mx, mn = a.max(1), a.min(1)
    lum = a.mean(1)
    sel = ((mx - mn) < 28) & (lum > 45) & (lum < 225)
    frac = float(sel.mean())
    if frac < 0.06:
        return None
    m = a[sel].mean(0)
    gains = m.mean() / np.maximum(m, 1e-6)
    return gains, frac


# ------------------------------------------------------------------ 1. QUALITY ANALYZER
def analyze_quality(path: str | Path | Image.Image, box: tuple[float, float, float, float] | None = None,
                    background: str | None = None) -> dict:
    """사진 품질 12항목. box(0~1)는 제품 위치를 알 때(사용자/Vision). 모르면 product_visibility 는 None(감점 안 함)."""
    img = path if isinstance(path, Image.Image) else _load(path)
    w, h = img.size
    g = _gray(img, 1024)
    arr = np.asarray(ImageOps.contain(img, (1024, 1024), Image.LANCZOS), dtype=np.float32)
    rgb_small = arr
    sharp = _lapvar(g)
    fb = focus_blur(g)
    edges = _sobel(g)
    noise = _noise_sigma(_gray(img, 2000))      # 축소하면 잡음이 줄어 과소평가되므로 원본에 가까운 해상도로
    lum = g
    mean_raw = float(lum.mean())
    sat0 = (rgb_small.max(2) - rgb_small.min(2))
    white_bg = float(((lum >= 235) & (sat0 < 40)).mean())
    # 흰 배경이 넓은 스튜디오 사진은 평균 밝기가 높은 게 정상 -> 흰 배경을 뺀 평균으로 노출 판단
    mean_l = float(lum[~((lum >= 235) & (sat0 < 40))].mean()) if white_bg > 0.25 and white_bg < 0.97 else mean_raw
    p1, p5, p95, p99 = np.percentile(lum, [1, 5, 95, 99])
    hi_clip = float((lum >= 250).mean())
    lo_clip = float((lum <= 5).mean())
    contrast = float(p95 - p5)
    wb = _neutral_gains(rgb_small)
    cast = float(np.abs(wb[0] - 1).max()) if wb else None
    # glare: 밝고 채도 낮은 큰 덩어리. reflection 은 정확한 측정이 불가능해 같은 신호의 보조 지표(휴리스틱)
    sat = (rgb_small.max(2) - rgb_small.min(2))
    glare = 0.0 if white_bg > 0.25 else float(((lum >= 250) & (sat < 40)).mean())
    # background complexity: 제품 밖 영역의 엣지 밀도
    eh, ew = edges.shape
    if box:
        x0, y0, x1, y1 = box
        m = np.ones((eh, ew), bool)
        m[int(y0 * eh):int(y1 * eh), int(x0 * ew):int(x1 * ew)] = False
    else:
        m = np.ones((eh, ew), bool)
        m[int(eh * 0.2):int(eh * 0.8), int(ew * 0.2):int(ew * 0.8)] = False
    bg_edge = float((edges[m] > 28).mean()) if m.any() else 0.0
    bg_complex = float(np.clip(bg_edge / 0.25, 0, 1))
    if background == "plain":
        bg_complex = min(bg_complex, 0.3)
    visibility = None
    if box:
        visibility = float(max(0.0, (box[2] - box[0]) * (box[3] - box[1])))
    core = _gray(img, min(1024, max(w, h)))
    block = _blockiness(np.asarray(ImageOps.contain(img, (1024, 1024), Image.LANCZOS).convert("L"), dtype=np.float32)
                        if max(w, h) <= 1024 else np.asarray(img.crop((0, 0, min(w, 1024), min(h, 1024))).convert("L"), dtype=np.float32))
    return {
        "resolution": [w, h], "min_side": min(w, h),
        "sharpness": round(sharp, 1),
        "blur": None if fb is None else round(fb, 3),                   # 0 선명 ~ 1 흐림 (가장 선명한 영역 기준)
        "noise": round(noise, 2),
        "exposure": {"mean": round(mean_l, 1), "mean_raw": round(mean_raw, 1), "white_background": round(white_bg, 3), "highlight_clip": round(hi_clip, 4), "shadow_clip": round(lo_clip, 4)},
        "white_balance_cast": None if cast is None else round(cast, 3),
        "contrast": round(contrast, 1),
        "glare": round(glare, 4),
        "reflection": round(min(1.0, glare * 4), 3),
        "background_complexity": round(bg_complex, 3),
        "product_visibility": None if visibility is None else round(visibility, 3),
        "compression_artifact": round(block, 3),
    }


def grade_photo(m: dict) -> tuple[str, list[str]]:
    """A(그대로) / B(보정 후) / C(품질 부족) 와 이유."""
    c_reasons, b_reasons = [], []
    if m["min_side"] < MIN_SIDE_C:
        c_reasons.append(f"해상도 부족 ({m['resolution'][0]}x{m['resolution'][1]})")
    blur = m.get("blur")
    if blur is not None and blur > 0.52:
        c_reasons.append(f"심하게 흐림 (초점 흐림 {blur:.2f})")
    elif blur is not None and blur > 0.38:
        b_reasons.append(f"약간 흐림 (초점 흐림 {blur:.2f})")
    ex = m["exposure"]
    if ex["mean"] < 45 or ex["mean"] > 225:
        c_reasons.append(f"노출 극단 (평균 밝기 {ex['mean']})")
    elif not 85 <= ex["mean"] <= 175:
        b_reasons.append(f"노출 보정 필요 (평균 밝기 {ex['mean']})")
    if ex["highlight_clip"] > 0.10:
        c_reasons.append(f"하이라이트 {ex['highlight_clip']:.0%} 날아감")
    elif ex["highlight_clip"] > 0.02:
        b_reasons.append(f"하이라이트 {ex['highlight_clip']:.1%} 날아감")
    if ex["shadow_clip"] > 0.12:
        b_reasons.append(f"그림자 {ex['shadow_clip']:.0%} 뭉침")
    if m["noise"] > 14:
        c_reasons.append(f"잡음 많음 ({m['noise']})")
    elif m["noise"] > 5:
        b_reasons.append(f"잡음 ({m['noise']})")
    if m["white_balance_cast"] is not None and m["white_balance_cast"] > 0.06:
        b_reasons.append(f"색 틀어짐 (화이트밸런스 {m['white_balance_cast']:.0%})")
    if m["contrast"] < 90:
        b_reasons.append(f"대비 낮음 ({m['contrast']})")
    if m["glare"] > 0.03:
        b_reasons.append(f"반사/빛 번짐 {m['glare']:.1%}")
    if m["compression_artifact"] > 1.4:
        b_reasons.append("압축 블록 노이즈")
    if m["background_complexity"] > 0.35:
        b_reasons.append(f"배경 복잡 ({m['background_complexity']:.2f}) - 보정으로 해결 불가, 촬영 배경 정리 필요")
    pv = m["product_visibility"]
    if pv is not None and pv < 0.08:
        c_reasons.append(f"제품이 너무 작음 (화면의 {pv:.0%})")
    elif pv is not None and pv < 0.2:
        b_reasons.append(f"제품이 작음 (화면의 {pv:.0%})")
    if m["min_side"] < 1200 and not c_reasons:
        b_reasons.append("해상도 낮음 (확대 제한)")
    if c_reasons:
        return "C", c_reasons + b_reasons
    if b_reasons:
        return "B", b_reasons
    return "A", []


# ------------------------------------------------------------------ 2. ENHANCEMENT STEPS
def _to_arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img, dtype=np.float32)


def _from_arr(a: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8))


def step_white_balance(a: np.ndarray, m: dict, ops: list) -> np.ndarray:
    wb = _neutral_gains(a)
    if wb is None or m["white_balance_cast"] is None or m["white_balance_cast"] < 0.03:
        return a
    gains = np.clip(wb[0], 0.93, 1.07)
    ops.append({"op": "white_balance", "gains": [round(float(x), 3) for x in gains], "neutral_pixels": round(wb[1], 3)})
    return np.clip(a * gains, 0, 255)


def step_exposure(a: np.ndarray, m: dict, ops: list) -> np.ndarray:
    """휘도 곡선: 평균 밝기를 목표로 감마, 그림자 리프트, 하이라이트 압축. 색 비율은 유지 (채도 불변)."""
    y = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32) / 255.0
    mean = float(y.mean())
    out = y.copy()
    applied = {}
    target = 0.47
    if not 0.33 <= mean <= 0.69:
        gamma = float(np.clip(np.log(target) / np.log(max(mean, 1e-3)), 0.7, 1.35))
        out = out ** gamma
        applied["gamma"] = round(gamma, 3)
    lo = float((y <= 0.02).mean())
    if lo > 0.03 or mean < 0.36:
        lift = 0.18 if lo > 0.08 else 0.10
        out = out + lift * (1 - out) ** 2 * (1 - out)
        applied["shadow_lift"] = lift
    if m["exposure"]["highlight_clip"] > 0.01 or m["glare"] > 0.02:
        k = 0.55
        knee = 0.82
        hi = out > knee
        out = np.where(hi, knee + (out - knee) * k, out)
        applied["highlight_compress"] = k
    if not applied:
        return a
    ratio = np.clip((out + 1e-4) / (y + 1e-4), 0.4, 2.5)
    ops.append({"op": "exposure", **applied})
    return np.clip(a * ratio[..., None], 0, 255)


def step_denoise(img: Image.Image, m: dict, ops: list) -> Image.Image:
    if m["noise"] <= 5:
        return img
    strength = float(np.clip((m["noise"] - 5) / 10, 0.25, 0.8))
    ycc = img.convert("YCbCr")
    y, cb, cr = ycc.split()
    cb = cb.filter(ImageFilter.GaussianBlur(2.0))
    cr = cr.filter(ImageFilter.GaussianBlur(2.0))
    y_med = y.filter(ImageFilter.MedianFilter(3))
    y = Image.blend(y, y_med, strength)
    ops.append({"op": "denoise", "luma_median_blend": round(strength, 2), "chroma_blur": 2.0})
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def step_sharpen(img: Image.Image, m: dict, ops: list) -> Image.Image:
    """소프트한 사진은 두 스케일 언샵으로 선명도 복원. 진짜 디컨볼루션이 아니므로 흐린 사진을 '복구'하지는 못한다."""
    blur = m.get("blur")
    if blur is None or blur <= 0.36:
        return img                                  # 이미 선명 (보케 배경이 흐린 건 의도된 것)
    scale = max(img.size) / 1080.0
    soft = blur > 0.45
    amt = 80 if soft else 45
    out = img.filter(ImageFilter.UnsharpMask(radius=max(0.8, 1.2 * scale), percent=amt, threshold=3))
    if soft:
        out = out.filter(ImageFilter.UnsharpMask(radius=max(2.0, 3.0 * scale), percent=35, threshold=4))
    ops.append({"op": "sharpen", "percent": amt, "two_scale": soft, "focus_blur": blur})
    return out


def step_contrast(a: np.ndarray, m: dict, ops: list) -> np.ndarray:
    """저대비 사진만 휘도 S커브를 약하게 (채도 불변)."""
    if m["contrast"] >= 130:
        return a
    amt = float(np.clip((130 - m["contrast"]) / 130 * 0.25, 0.04, 0.12))
    y = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32) / 255.0
    s = (1 - amt) * y + amt * (y * y * (3 - 2 * y))   # smoothstep 혼합 = 약한 S커브
    ratio = np.clip((s + 1e-4) / (y + 1e-4), 0.7, 1.4)
    ops.append({"op": "contrast", "amount": round(amt, 3)})
    return np.clip(a * ratio[..., None], 0, 255)


def step_upscale(img: Image.Image, grade: str, ops: list) -> Image.Image:
    short = min(img.size)
    if grade == "C" or short >= UPSCALE_TARGET or short < MIN_SIDE_C:
        return img
    k = min(MAX_UPSCALE, UPSCALE_TARGET / short)
    new = (round(img.width * k), round(img.height * k))
    out = img.resize(new, Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.0, percent=25, threshold=3))
    ops.append({"op": "upscale", "factor": round(k, 3), "method": "lanczos (디테일 생성 없음)"})
    return out


def enhance_image(img: Image.Image, m: dict, grade: str, level: str = "full") -> tuple[Image.Image, list]:
    """level: full(전체) | safe(노출+약한 선명도만, 색은 손대지 않음)."""
    ops: list[dict] = []
    if max(img.size) > MAX_WORK_SIDE:
        img = ImageOps.contain(img, (MAX_WORK_SIDE, MAX_WORK_SIDE), Image.LANCZOS)
        ops.append({"op": "downscale_for_video", "to_long_side": MAX_WORK_SIDE})
    a = _to_arr(img)
    if level == "full":
        a = step_white_balance(a, m, ops)
    a = step_exposure(a, m, ops)
    out = _from_arr(a)
    if level == "full":
        out = step_denoise(out, m, ops)
        a = step_contrast(_to_arr(out), m, ops)
        out = _from_arr(a)
    out = step_sharpen(out, m, ops)
    if level == "full":
        out = step_upscale(out, grade, ops)
    return out, ops


# ------------------------------------------------------------------ 3. BACKGROUND ROUTER
def background_route(m: dict, cutout_ok: bool | None, background: str | None) -> dict:
    """제품 배경 처리 결정 (실제 처리는 motion.py 의 hero/macro plate 가 이 결정에 따라 수행)."""
    if cutout_ok:
        return {"route": "studio_cutout", "why": "배경 제거가 신뢰 가능 -> 스튜디오 배경 + 그림자"}
    if m["background_complexity"] > 0.35 or background == "busy":
        return {"route": "original_tight", "why": "복잡한 배경 -> 원본 유지 + 제품 중심 크롭, 확대 제한"}
    return {"route": "original_blur_fill", "why": "원본 유지 + 흐린 배경 채움"}


# ------------------------------------------------------------------ 4. PRODUCT FIDELITY QA
def fidelity_local(original: Image.Image, enhanced: Image.Image, box: tuple[float, float, float, float] | None = None,
                   wb_applied: bool = False) -> dict:
    """구조(엣지 상관), 같은 위치 픽셀의 색상각/채도 변화, 비율 변화를 측정. 통과 못 하면 보정본 폐기.
    화이트밸런스를 적용한 보정은 색이 조금 옮겨가는 게 정상이라 색상 허용치를 넓힌다 (Vision 판정이 최종 확인)."""
    o = ImageOps.contain(original, (512, 512))
    e = enhanced.resize(o.size, Image.LANCZOS)
    go, ge = np.asarray(o.convert("L"), dtype=np.float32), np.asarray(e.convert("L"), dtype=np.float32)
    eo, ee = _sobel(go), _sobel(ge)
    eo, ee = eo - eo.mean(), ee - ee.mean()
    corr = float((eo * ee).sum() / (np.sqrt((eo ** 2).sum() * (ee ** 2).sum()) + 1e-9))
    ho, he = np.asarray(o.convert("HSV"), dtype=np.float32), np.asarray(e.convert("HSV"), dtype=np.float32)
    sel = (ho[..., 1] > 90) & (he[..., 1] > 90) & (ho[..., 2] > 70) & (he[..., 2] > 70)     # 양쪽 다 색이 분명한 같은 위치 픽셀
    if box:
        h, w = sel.shape
        m = np.zeros_like(sel)
        m[int(box[1] * h):int(box[3] * h), int(box[0] * w):int(box[2] * w)] = True
        sel = sel & m
    if sel.sum() < 200:
        hue_shift, chroma_change = 0.0, 0.0
    else:
        d = (he[..., 0][sel] - ho[..., 0][sel]) / 255 * 360
        d = (d + 180) % 360 - 180
        hue_shift = float(abs(np.median(d)))
        chroma_change = float(abs(np.median(he[..., 1][sel]) - np.median(ho[..., 1][sel])) / max(np.median(ho[..., 1][sel]), 1.0))
    hue_max = HUE_SHIFT_MAX_WB if wb_applied else HUE_SHIFT_MAX
    aspect_change = abs((enhanced.width / enhanced.height) / (original.width / original.height) - 1)
    ok = corr >= EDGE_CORR_MIN and hue_shift <= hue_max and chroma_change <= (CHROMA_CHANGE_MAX_WB if wb_applied else CHROMA_CHANGE_MAX) and aspect_change < 0.003
    return {"edge_correlation": round(corr, 4), "hue_shift_deg": round(hue_shift, 2), "chroma_change": round(chroma_change, 3),
            "aspect_change": round(aspect_change, 5), "ok": ok}


FIDELITY_SYSTEM = (
    "You compare an ORIGINAL product photo (image 1) with an ENHANCED version (image 2) for a shopping video. "
    "Answer JSON only. Judge whether the product itself is unchanged. The ONLY allowed differences are brightness, contrast, "
    "sharpness, noise, and mild white balance. Report any change to: product shape, proportions, colors, button/port positions, "
    "logo, product name, label or printed text, feature positions (e.g. LED ring), or any added/removed/hallucinated detail. "
    'Schema: {"fidelity":0-100,"shape_changed":false,"color_changed":false,"text_or_logo_changed":false,'
    '"details_added_or_removed":false,"notes":"short"}. fidelity 95-100 = identical product, only lighting/sharpness differ; '
    "below 90 = visible product change."
)


def fidelity_vision(router, original: Path, enhanced: Path, work_dir: Path) -> dict | None:
    if router is None or not router.has_real("vision"):
        return None
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        imgs = []
        for i, p in enumerate((original, enhanced)):
            im = ImageOps.contain(_load(p), (1024, 1024))
            dst = work_dir / f"cmp_{Path(original).stem}_{i}.jpg"
            im.save(dst, quality=90)
            imgs.append(str(dst))
        v = router.run("vision", "json", system=FIDELITY_SYSTEM, user="Image 1 = ORIGINAL, image 2 = ENHANCED.",
                       images=imgs, temperature=0).value
        if not isinstance(v, dict):
            return {"error": "invalid response"}
        v["fidelity"] = int(v.get("fidelity", 0) or 0)
        return v
    except Exception as e:
        return {"error": str(e)[:200]}


def _fidelity_pass(local: dict, vis: dict | None) -> tuple[bool, str]:
    if not local["ok"]:
        return False, f"로컬 검사 실패 (엣지 {local['edge_correlation']}, 색상 이동 {local['hue_shift_deg']}°, 채도 변화 {local['chroma_change']})"
    if vis is None:
        return True, "로컬 검사 통과 (Vision 비교 불가)"
    if vis.get("error"):
        return True, "로컬 검사 통과 (Vision 비교 실패: 원본 대조 없음)"
    bad = [k for k in ("shape_changed", "color_changed", "text_or_logo_changed", "details_added_or_removed") if vis.get(k)]
    if vis["fidelity"] < FIDELITY_MIN or bad:
        return False, f"Vision Fidelity {vis['fidelity']} {bad} {vis.get('notes', '')}"
    return True, f"Vision Fidelity {vis['fidelity']}"


# ------------------------------------------------------------------ 5. PIPELINE ENTRY
def process_photos(photos: list[str], out_dir: Path, router=None,
                   boxes: dict[str, tuple] | None = None, backgrounds: dict[str, str] | None = None,
                   cutouts: dict[str, bool] | None = None) -> dict:
    """photos(원본 경로) -> {"photos": [...], "effective": [사용할 경로], "summary": ...}.
    ORIGINAL 은 그대로, ENHANCED 는 out_dir/enhanced, 비교 자료는 out_dir/derived."""
    enh_dir, der_dir = Path(out_dir) / "enhanced", Path(out_dir) / "derived"
    enh_dir.mkdir(parents=True, exist_ok=True)
    der_dir.mkdir(parents=True, exist_ok=True)
    boxes, backgrounds, cutouts = boxes or {}, backgrounds or {}, cutouts or {}
    report, effective = [], []
    for i, p in enumerate(photos):
        orig_img = _load(p)
        box = boxes.get(p)
        bg = backgrounds.get(p)
        before = analyze_quality(orig_img, box, bg)
        grade, reasons = grade_photo(before)
        item = {"index": i, "original": p, "grade_before": grade, "grade_text": GRADE_TEXT[grade], "reasons": reasons,
                "metrics_before": before, "decision": "original", "enhanced": None, "ops": [], "fidelity": None,
                "background": background_route(before, cutouts.get(p), bg)}
        use = p
        if grade == "A":
            item["decision"] = "original (A: 보정 불필요)"
        elif grade == "C":
            item["decision"] = "original (C: 품질 부족 - 억지로 보정/확대하지 않음)"
        else:
            attempts = []
            for level in ("full", "safe"):
                enhanced_img, ops = enhance_image(orig_img, before, grade, level)
                if not [o for o in ops if o["op"] != "downscale_for_video"]:
                    attempts.append({"level": level, "ok": True, "why": "보정할 항목 없음", "local": None, "vision": None, "file": None})
                    failed_full = any(a["level"] == "full" and not a["ok"] for a in attempts)
                    item["decision"] = ("original (전체 보정은 충실도 검사 실패, 안전 보정 항목 없음)" if failed_full
                                        else "original (보정할 항목 없음 - 배경/구도 문제는 보정 대상이 아님)")
                    break
                dst = enh_dir / f"{Path(p).stem}_{level}.jpg"
                enhanced_img.save(dst, quality=95, subsampling=0)
                local = fidelity_local(orig_img, enhanced_img, box, wb_applied=any(o['op'] == 'white_balance' for o in ops))
                vis = fidelity_vision(router, Path(p), dst, der_dir)
                ok, why = _fidelity_pass(local, vis)
                attempts.append({"level": level, "ok": ok, "why": why, "local": local, "vision": vis, "ops": ops, "file": str(dst)})
                if ok:
                    use = str(dst)
                    item.update({"decision": f"enhanced:{level}", "enhanced": str(dst), "ops": ops,
                                 "fidelity": {"local": local, "vision": vis, "verdict": why}})
                    break
            item["attempts"] = [{k: v for k, v in a.items() if k not in ("ops",)} for a in attempts]
            if use == p and "보정할 항목 없음" not in item["decision"]:
                item["decision"] = "original (보정본이 제품 충실도 검사 실패 -> 폐기)"
        after_img = _load(use) if use != p else orig_img
        after = analyze_quality(after_img, box, bg)
        item["metrics_after"] = after
        item["grade_after"] = grade_photo(after)[0]
        item["effective"] = use
        effective.append(use)
        report.append(item)
    grades = [r["grade_before"] for r in report]
    summary = {"before": {g: grades.count(g) for g in "ABC"},
               "after": {g: [r["grade_after"] for r in report].count(g) for g in "ABC"},
               "enhanced": sum(1 for r in report if r["decision"].startswith("enhanced")),
               "discarded": sum(1 for r in report if "폐기" in r["decision"])}
    (der_dir / "photo_quality.json").write_text(json.dumps({"photos": report, "summary": summary}, ensure_ascii=False, indent=2,
                                                            default=str), encoding="utf-8")
    return {"photos": report, "effective": effective, "summary": summary}
