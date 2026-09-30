"""VISION PRODUCT ANALYSIS (Gemini 등 Vision LLM).

사람이 하던 두 가지를 자동으로 채운다:
  1) 복잡한 배경 사진의 제품 위치 박스 (product_boxes)
  2) 특징 문장 -> 그 특징이 보이는 사진 (feature_photos)

원칙: 사진에 보이는 것만. 확실하지 않으면 null/UNKNOWN. 효능/성능/판매량/인증을 추정하지 않는다.
사용자가 이미 지정한 값(박스/연결)은 덮어쓰지 않는다.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE = 1024

SYSTEM = (
    "You analyze product photos for a shopping-video pipeline. Answer with JSON only. "
    "Describe ONLY what is visibly present. If unsure, use null or \"UNKNOWN\". "
    "Never infer performance, health effects, sales numbers, certifications, or claims. "
    "Boxes are normalized [x0,y0,x1,y1] in 0..1 relative to the image AFTER upright orientation, "
    "tightly around the MAIN product (not the whole scene, not screens or people)."
)


def prepare_images(photos: list[str], out_dir: Path) -> list[str]:
    """Vision 호출용으로 긴 변 1024px 로 줄인 사본 (원본은 건드리지 않음)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, p in enumerate(photos):
        with Image.open(p) as im:
            img = ImageOps.exif_transpose(im).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        dst = out_dir / f"v{i}.jpg"
        img.save(dst, quality=88)
        out.append(str(dst))
    return out


def build_prompt(features: list[str], n: int) -> str:
    feats = "\n".join(f"- {f}" for f in features) or "(none provided)"
    return (
        f"There are {n} photos of the same product, in order (index 0..{n - 1}).\n"
        f"Product features provided by the seller (Korean):\n{feats}\n\n"
        "Return JSON with exactly this shape:\n"
        '{"photos":[{"index":0,"product_present":true,"box":[x0,y0,x1,y1] or null,'
        '"angle":"front|side|top|detail|usage|other","background":"plain|busy",'
        '"visible_text":["text printed on the product or its packaging"],'
        '"visible_features":["short factual phrases of what is visible"],'
        '"private_info_visible":["e.g. map with street names, license plate, faces, addresses (empty if none)"]}],'
        '"brand_or_name_visible":"text visible on product or UNKNOWN",'
        '"category_guess":"one of: 생활, 주방, 전자기기, 뷰티, 운동, 유아, 패션, UNKNOWN",'
        '"feature_photo":{"<feature text exactly as provided>": photo index where that feature is best visible, or null}}'
    )


def _valid_box(b) -> list[float] | None:
    try:
        x0, y0, x1, y1 = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    if (x1 - x0) * (y1 - y0) < 0.04:      # 너무 작은 박스는 신뢰하지 않음
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def _parse(data: dict, n: int) -> tuple[dict, list, dict]:
    boxes, per_photo = {}, []
    for item in data.get("photos", []) if isinstance(data.get("photos"), list) else []:
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < n:
            continue
        present = item.get("product_present", True)
        box = _valid_box(item.get("box")) if present else None
        if box:
            boxes[idx] = box
        per_photo.append({"index": idx, "box": box, "present": bool(present), "angle": item.get("angle"),
                          "background": item.get("background"),
                          "visible_text": [str(t) for t in item.get("visible_text", [])][:8],
                          "visible_features": [str(t) for t in item.get("visible_features", [])][:8],
                          "private_info_visible": [str(t) for t in item.get("private_info_visible", [])][:6]})
    return boxes, per_photo, data


def analyze(router, photos: list[str], features: list[str], work_dir: Path) -> dict | None:
    """Vision provider 가 없으면 None. 실패해도 파이프라인은 계속되도록 예외를 삼킨다.
    제품이 있는 사진인데 박스가 빠졌으면 1회 재시도해서 채운다 (temperature 0 으로 재현성 확보)."""
    if router is None or not router.has_real("vision") or not photos:
        return None
    try:
        images = prepare_images(photos, work_dir / "vision")
        prompt = build_prompt(features, len(photos))
        res = router.run("vision", "json", system=SYSTEM, user=prompt, images=images, temperature=0)
        data = res.value if isinstance(res.value, dict) else {}
        boxes, per_photo, _ = _parse(data, len(photos))
        missing = [ph["index"] for ph in per_photo if ph["present"] and ph["index"] not in boxes]
        usage_in, usage_out, cost = res.usage.input_units, res.usage.output_units, res.usage.estimated_cost
        if missing:   # 박스 누락 사진만 다시 요청
            res2 = router.run("vision", "json", system=SYSTEM, temperature=0,
                              user=prompt + f"\nIMPORTANT: photos {missing} MUST include a valid tight box around the main product.",
                              images=images)
            boxes2, per2, _ = _parse(res2.value if isinstance(res2.value, dict) else {}, len(photos))
            for idx in missing:
                if idx in boxes2:
                    boxes[idx] = boxes2[idx]
                    for ph in per_photo:
                        if ph["index"] == idx:
                            ph["box"] = boxes2[idx]
            usage_in += res2.usage.input_units
            usage_out += res2.usage.output_units
            cost += res2.usage.estimated_cost
    except Exception as e:
        return {"error": str(e)[:300], "provider": None}
    links = {}
    fp = data.get("feature_photo") if isinstance(data.get("feature_photo"), dict) else {}
    for feat in features:
        idx = fp.get(feat)
        if isinstance(idx, int) and 0 <= idx < len(photos):
            links[feat] = idx
    return {"provider": f"{res.provider}:{res.model}", "boxes": boxes, "feature_links": links, "photos": per_photo,
            "brand_or_name_visible": data.get("brand_or_name_visible"), "category_guess": data.get("category_guess"),
            "usage": {"in": usage_in, "out": usage_out, "cost": cost}}
