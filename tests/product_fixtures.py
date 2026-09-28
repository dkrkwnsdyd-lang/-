"""테스트용 제품 사진 생성기.

이 샌드박스는 외부 이미지 사이트 접근이 막혀 있어서 실제 상품 사진 대신
음영이 들어간 합성 제품 사진(스튜디오 흰 배경 + 생활 배경)을 만든다.
실제 품질 평가는 진짜 상품 사진으로 다시 해야 한다 (TEST_RESULTS.md 참고).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1600


def _shade_cylinder(w, h, color, light=0.35):
    xs = np.linspace(-1, 1, w)
    shade = np.clip(0.55 + 0.45 * np.sqrt(np.clip(1 - xs ** 2, 0, 1)) - light * np.clip(xs, 0, 1) ** 2, 0, 1.2)
    spec = np.exp(-((xs + 0.45) / 0.08) ** 2) * 0.5
    col = np.array(color, np.float32)[None, :] * shade[:, None] + 255 * spec[:, None]
    return np.repeat(np.clip(col, 0, 255)[None, :, :], h, axis=0).astype(np.uint8)


def _studio(bg=(244, 244, 242)):
    img = Image.new("RGB", (S, S), bg)
    d = ImageDraw.Draw(img)
    d.ellipse([S * 0.25, S * 0.86, S * 0.75, S * 0.93], fill=tuple(int(c * 0.9) for c in bg))
    return img.filter(ImageFilter.GaussianBlur(3))


def _lifestyle(product: Image.Image, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = np.zeros((S, S, 3), np.float32)
    wood = np.array([150, 110, 72], np.float32)
    grain = (np.sin(np.linspace(0, 60, S))[None, :] * 12 + rng.normal(0, 6, (S, S)))[..., None]
    base[:] = wood + grain
    base[: S // 2] = np.array([205, 200, 190]) + rng.normal(0, 3, (S // 2, S, 3))
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5))
    p = product.copy()
    p.thumbnail((int(S * 0.75), int(S * 0.75)))
    mask = Image.fromarray((np.asarray(p.convert("L")) < 236).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1))
    img.paste(p, ((S - p.width) // 2, int(S * 0.55 - p.height / 2)), mask)
    return img


def _label(d, xy, text, size, fill):
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/nanum/NanumSquareB.ttf", size)
    except OSError:
        f = ImageFont.load_default(size=size)
    d.text(xy, text, font=f, fill=fill, anchor="mm")


def tumbler():
    img = _studio()
    w, h = 420, 1000
    body = Image.fromarray(_shade_cylinder(w, h, (70, 120, 110)))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], 60, fill=255)
    img.paste(body, ((S - w) // 2, 380), m)
    lid = Image.fromarray(_shade_cylinder(w + 30, 170, (40, 40, 44)))
    lm = Image.new("L", lid.size, 0)
    ImageDraw.Draw(lm).rounded_rectangle([0, 0, lid.width - 1, lid.height - 1], 40, fill=255)
    img.paste(lid, ((S - lid.width) // 2, 240), lm)
    d = ImageDraw.Draw(img)
    _label(d, (S // 2, 820), "KEEP", 70, (230, 235, 230))
    return img


def earbuds():
    img = _studio((236, 238, 242))
    d = ImageDraw.Draw(img)
    case = Image.fromarray(_shade_cylinder(760, 560, (250, 250, 252), light=0.2))
    m = Image.new("L", case.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, 759, 559], 230, fill=255)
    img.paste(case, (420, 620), m)
    d.line([430, 800, 1170, 800], fill=(190, 190, 196), width=4)
    d.ellipse([780, 1040, 820, 1080], fill=(80, 200, 120))
    d.rounded_rectangle([760, 1110, 840, 1125], 6, fill=(170, 170, 175))
    return img


def serum():
    img = _studio((246, 240, 236))
    w, h = 360, 760
    body = Image.fromarray(_shade_cylinder(w, h, (200, 140, 90), light=0.25))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], 50, fill=255)
    img.paste(body, ((S - w) // 2, 640), m)
    cap = Image.fromarray(_shade_cylinder(150, 180, (30, 30, 30)))
    img.paste(cap, ((S - 150) // 2, 470))
    bulb = Image.new("L", (190, 200), 0)
    ImageDraw.Draw(bulb).ellipse([0, 0, 189, 199], fill=255)
    img.paste(Image.fromarray(_shade_cylinder(190, 200, (25, 25, 25))), ((S - 190) // 2, 300), bulb)
    d = ImageDraw.Draw(img)
    d.rectangle([(S - w) // 2 + 40, 900, (S + w) // 2 - 40, 1150], fill=(245, 238, 228))
    _label(d, (S // 2, 980), "SERUM", 52, (60, 50, 40))
    _label(d, (S // 2, 1060), "30ml", 40, (90, 80, 70))
    return img


def massage_gun():
    img = _studio((240, 240, 240))
    d = ImageDraw.Draw(img)
    head = Image.fromarray(_shade_cylinder(900, 300, (45, 48, 55)))
    hm = Image.new("L", head.size, 0)
    ImageDraw.Draw(hm).rounded_rectangle([0, 0, 899, 299], 140, fill=255)
    img.paste(head, (330, 420), hm)
    handle = Image.fromarray(_shade_cylinder(230, 720, (45, 48, 55)))
    hm2 = Image.new("L", handle.size, 0)
    ImageDraw.Draw(hm2).rounded_rectangle([0, 0, 229, 719], 90, fill=255)
    img.paste(handle, (700, 640), hm2)
    d.ellipse([160, 470, 380, 670], fill=(230, 110, 40))
    for i in range(4):
        d.ellipse([790, 820 + i * 55, 820, 850 + i * 55], fill=(80, 200, 255) if i < 3 else (60, 60, 60))
    d.ellipse([770, 1080, 840, 1150], fill=(20, 20, 22), outline=(120, 120, 130), width=5)
    return img


def basket():
    img = _studio((244, 242, 238))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 300, 560, 1300, 1260
    d.rounded_rectangle([x0, y0, x1, y1], 60, fill=(214, 190, 150))
    for y in range(y0 + 40, y1, 60):
        d.line([x0 + 20, y, x1 - 20, y], fill=(180, 150, 110), width=10)
    for x in range(x0 + 50, x1, 90):
        d.line([x, y0 + 20, x, y1 - 20], fill=(195, 168, 128), width=6)
    d.rounded_rectangle([700, 600, 900, 660], 30, fill=(120, 90, 60))
    return img


PRODUCTS = {
    "living_basket": {"make": basket, "name": "라탄 수납 바스켓", "category": "생활",
                      "features": ["손잡이 달린 대용량", "접이식이라 보관 간편"], "problem": "거실 물건이 여기저기 흩어져요"},
    "kitchen_tumbler": {"make": tumbler, "name": "보온보냉 스텐 텀블러", "category": "주방",
                        "features": ["원터치 뚜껑", "컵홀더에 쏙 들어가는 슬림형", "세척이 쉬운 넓은 입구"],
                        "problem": "텀블러 뚜껑 여는 게 번거로워요"},
    "electronics_earbuds": {"make": earbuds, "name": "무선 블루투스 이어폰", "category": "전자기기",
                            "features": ["손바닥보다 작은 케이스", "USB-C 충전", "잔량 LED 표시"], "problem": ""},
    "beauty_serum": {"make": serum, "name": "비타민 세럼 30ml", "category": "뷰티",
                     "features": ["스포이드 타입", "가볍게 스며드는 제형"], "problem": "아침마다 화장이 들떠요"},
    "fitness_massage_gun": {"make": massage_gun, "name": "무선 미니 마사지건", "category": "운동",
                            "features": ["4단계 강도 조절", "USB-C 충전", "손에 쏙 들어오는 크기"],
                            "problem": "운동 끝나면 어깨가 뭉쳐요"},
}


def make_photos(key: str, out_dir: Path, n: int = 3) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = PRODUCTS[key]["make"]()
    paths = []
    front = out_dir / f"{key}_front.jpg"
    img.save(front, quality=93)
    paths.append(str(front))
    if n >= 2:
        side = img.rotate(8, resample=Image.BICUBIC, fillcolor=img.getpixel((5, 5))).crop((80, 80, S - 80, S - 80))
        p = out_dir / f"{key}_angle.jpg"
        side.save(p, quality=93)
        paths.append(str(p))
    if n >= 3:
        p = out_dir / f"{key}_life.jpg"
        _lifestyle(img, hash(key) % 1000).save(p, quality=93)
        paths.append(str(p))
    return paths
