"""Opt-in MOSS-Image SFT backgrounds for SHOP SHORTS AI.

MOSS is text-to-image, NOT identity-preserving image-to-image. The original
product photo is only composited afterward, never sent for regeneration.
The module is inert unless a caller explicitly requests and approves generation.
Docs: https://platform.mosi.cn/en/docs/reference/images-generations/
"""
from __future__ import annotations

import io
import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

API_ENDPOINT = "https://api.mosi.cn/v1/images/generations"
MODELS = ("moss-image-sft-1.0", "moss-image-base-1.0")
DEFAULT_SIZE = "720x1280"  # exactly 9:16; 16-pixel aligned
MAX_BYTES = 20 * 1024 * 1024
NEGATIVE = "text, letters, watermark, logo, product, packaging, nsfw, worst quality, jpeg artifact"

STYLE_HINTS = {
    "lifestyle": "Bright contemporary living room, natural light, soft cream and warm neutral palette",
    "kitchen": "Minimal modern kitchen counter, daylight, clean natural surfaces",
    "tech": "Premium modern studio, dark navy backdrop, subtle cyan accents, soft rim lighting",
    "beauty": "Soft beige cosmetic photography studio, warm diffusion and clean marble surface",
}


def validate_size(size: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", size)
    if not match:
        raise ValueError("이미지 크기는 720x1280과 같은 형식이어야 합니다.")
    width, height = map(int, match.groups())
    if not (256 <= width <= 2048 and 256 <= height <= 2048
            and width % 16 == 0 and height % 16 == 0
            and width * height <= 2097152):
        raise ValueError("각 변 256~2048, 16의 배수, 총 2,097,152픽셀 이하만 지원합니다.")
    return width, height


def make_plan(scene: str = "", *, style: str = "lifestyle",
              model: str = "moss-image-sft-1.0",
              size: str = DEFAULT_SIZE, headline: str = "", product_name: str = "") -> dict:
    if model not in MODELS:
        raise ValueError("지원하지 않는 MOSS-Image 모델입니다.")
    if style not in STYLE_HINTS:
        raise ValueError("알 수 없는 배경 스타일입니다.")
    validate_size(size)
    if len(headline) > 90:
        raise ValueError("제목은 90자를 넘을 수 없습니다.")
    if len(product_name) > 120:
        raise ValueError("상품명은 120자를 넘을 수 없습니다.")
    if len(scene) > 1300:
        raise ValueError("장면 설명이 너무 깁니다.")
    scene_desc = scene.strip() or "a generous empty central presentation surface"
    prompt = (
        f"Vertical professional commercial photography BACKGROUND ONLY. {STYLE_HINTS[style]}. "
        f"Art direction: {scene_desc}. Leave generous clean negative space in the center for "
        "a real product photograph to be composited later. NO product, NO hands, NO labels, "
        "NO graphics, NO words, NO logos, NO packaging, NO invented product features. "
        "Photorealistic lighting, balanced composition, high-quality environment."
    )
    if len(prompt) > 4000:
        raise ValueError("프롬프트 최대 길이를 초과했습니다.")
    return {
        "provider": "MOSI", "model": model, "size": size, "style": style,
        "headline": headline.strip(), "product_name": product_name.strip(),
        "prompt": prompt, "negative_prompt": NEGATIVE,
        "type": "BACKGROUND_ONLY", "identity_preserved": "COMPOSITE_ORIGINAL_PHOTO",
        "paid_call_required": True,
    }


def _request(plan: dict) -> dict:
    if plan.get("model") not in MODELS:
        raise ValueError("유효하지 않은 모델입니다.")
    validate_size(plan.get("size", ""))
    prompt = plan.get("prompt", "")
    if not isinstance(prompt, str) or not prompt or len(prompt) > 4000:
        raise ValueError("프롬프트는 1~4000자만 지원합니다.")
    return {
        "model": plan["model"], "prompt": prompt,
        "negative_prompt": NEGATIVE, "size": plan["size"],
        "n": 1, "response_format": "url",
    }


def _check_https_url(url: str) -> None:
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.port not in (None, 443)):
        raise ValueError("MOSS 결과 URL은 안전한 HTTPS 주소여야 합니다.")
    host = parts.hostname.lower().strip(".")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("로컬 주소로의 이미지 다운로드는 차단됩니다.")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("사설 네트워크 주소로의 다운로드는 차단됩니다.")
    except ValueError as ex:
        if "차단됩니다" in str(ex):
            raise


def generate_background(plan: dict, out_file: str | Path, *, approve_paid: bool = False,
                        api_key: str | None = None, http=None) -> dict:
    """Calls the paid API ONLY after explicit approval. Key never stored in output."""
    if not approve_paid:
        raise PermissionError("MOSS 이미지 생성은 유료일 수 있습니다. 명시적 비용 승인이 필요합니다.")
    key = api_key or os.environ.get("MOSS_API_KEY")
    if not key:
        raise ValueError("MOSS_API_KEY가 설정되지 않았습니다. 실제 API 호출은 하지 않았습니다.")
    payload = _request(plan)
    http = http or requests
    try:
        response = http.post(
            API_ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload, timeout=(15, 900), allow_redirects=False)
        response.raise_for_status()
        result = response.json()
        image_url = result["data"][0]["url"]
        _check_https_url(image_url)
        image_response = http.get(image_url, stream=True, timeout=(15, 90), allow_redirects=False)
        image_response.raise_for_status()
        if 300 <= image_response.status_code < 400:
            raise ValueError("예상하지 못한 이미지 URL 이동을 차단했습니다.")
        if not image_response.headers.get("Content-Type", "").lower().startswith("image/"):
            raise ValueError("결과 다운로드가 이미지가 아닙니다.")
        buffer = bytearray()
        for chunk in image_response.iter_content(chunk_size=65536):
            buffer.extend(chunk)
            if len(buffer) > MAX_BYTES:
                raise ValueError("이미지 크기 제한(20MB)을 초과했습니다.")
        with Image.open(io.BytesIO(buffer)) as src:
            src.load()
            if src.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("이미지 형식이 지원되지 않습니다.")
            img = ImageOps.exif_transpose(src).convert("RGB")
        if img.width * img.height > 20_000_000:
            raise ValueError("결과 이미지가 너무 큽니다.")
        path = Path(out_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, format="PNG")
        return {"file": str(path), "usage": result.get("usage") or {},
                "model": payload["model"], "provider": "MOSI", "paid_request": True}
    except requests.RequestException as exc:
        # Never include remote error bodies, headers or API keys in logs.
        raise RuntimeError("MOSS API 또는 이미지 다운로드 오류: 응답 상태와 네트워크를 확인하세요.") from None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "C:/Windows/Fonts/malgunbd.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def compose_cover(background: str | Path, original_photo: str | Path | None,
                  headline: str, output: str | Path) -> Path:
    """Make a cover WITHOUT modifying the actual product pixels/source file.

    Original product is shown in a contained image-card; this intentionally
    avoids unreliable product cutout or AI reconstruction.
    """
    if len(headline) > 90:
        raise ValueError("제목은 90자를 넘을 수 없습니다.")
    with Image.open(background) as raw:
        canvas = ImageOps.exif_transpose(raw).convert("RGB")
    w, h = canvas.size
    canvas = canvas.copy()
    draw = ImageDraw.Draw(canvas, "RGBA")
    top_h = int(h * .24)
    draw.rectangle((0, 0, w, top_h), fill=(0, 0, 0, 155))
    title = headline.strip()
    if title:
        font = _font(max(18, min(62, w // 12)))
        # Pixel measured wrap, keep at most three lines.
        rows = []
        line = ""
        for part in title.split():
            trial = f"{line} {part}".strip()
            if draw.textbbox((0, 0), trial, font=font)[2] > w - 56 and line:
                rows.append(line)
                line = part
            else:
                line = trial
        if line:
            rows.append(line)
        for i, row in enumerate(rows[:3]):
            draw.text((w // 2, int(h * .055) + i * int(font.size * 1.26)),
                      row, font=font, anchor="mt", fill=(255, 255, 255, 255))
    if original_photo:
        with Image.open(original_photo) as source:
            photo = ImageOps.exif_transpose(source).convert("RGBA")
        card_w, card_h = int(w * .79), int(h * .48)
        contained = ImageOps.contain(photo, (card_w - 28, card_h - 28))
        card = Image.new("RGBA", (card_w, card_h), (255, 255, 255, 246))
        x, y = (card_w - contained.width) // 2, (card_h - contained.height) // 2
        card.alpha_composite(contained, (x, y))
        base = canvas.convert("RGBA")
        base.alpha_composite(card, ((w - card_w) // 2, int(h * .36)))
        canvas = base.convert("RGB")
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG")
    return out


def plan_from_job(result_json: str | Path, **overrides) -> tuple[dict, Path | None]:
    """Reuse established product identity but never invent missing facts."""
    file = Path(result_json).resolve()
    result = json.loads(file.read_text(encoding="utf-8"))
    if result.get("status") in ("FAILED", "STRATEGY_BLOCKED"):
        raise ValueError("실패한 작업은 이미지 생성에 사용할 수 없습니다.")
    identity = result.get("identity") or {}
    name = identity.get("name") or ""
    photos = identity.get("photos") or []
    image_path = None
    for photo in photos:
        if not isinstance(photo, dict) or not photo.get("path"):
            continue
        candidate = Path(photo["path"])
        candidates = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, file.parent / candidate]
        image_path = next((x for x in candidates if x.is_file()), None)
        if image_path:
            break
    args = {"product_name": name, "headline": name, **overrides}
    return make_plan(**args), image_path
