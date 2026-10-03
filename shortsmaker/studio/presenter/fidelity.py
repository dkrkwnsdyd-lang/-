"""PRODUCT FIDELITY QA: AI 인물이 상품을 들거나 쓰는 장면은 원본 상품과 비교한다.

판정: PASS | PRODUCT_MISMATCH | UNVERIFIED(비교할 수단이 없음) | NOT_APPLICABLE(상품이 안 나오는 장면)
- 비교할 Vision 이 없으면 UNVERIFIED 이고, UNVERIFIED 는 최종 영상에 쓰지 않는다 (확인 못 한 상품 장면을 내보내지 않는다).
- PRODUCT_MISMATCH 인 장면은 최종 영상에서 제외하고 원본 상품 영상/사진으로 대체한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ...video import ffmpeg_exe

FIDELITY_MIN = 85
CHECKS = ("shape_changed", "color_changed", "logo_or_text_changed", "button_or_part_changed", "pattern_changed", "proportion_changed",
          "hand_anatomy_problem", "hand_product_intersection", "product_duplicate", "product_morph")

SYSTEM = (
    "You compare a REAL product reference photo (image 1) with frames from an AI-generated video where a person holds/uses a product (images 2+). "
    "Decide whether the product in the video is the SAME product as in the reference: shape, color, logo/printed text, button positions, parts, "
    "pattern, size proportion, distinctive exterior. Be strict: if the product looks like a different or generic item, say so. "
    "Also inspect physical interaction quality whenever hands are visible: natural finger count/anatomy, believable grip/contact, no fingers passing through the product, "
    "no duplicated product, and no product melting/morphing/resizing across frames. "
    'Answer JSON only: {"same_product":true,"fidelity":0-100,"shape_changed":false,"color_changed":false,"logo_or_text_changed":false,'
    '"button_or_part_changed":false,"pattern_changed":false,"proportion_changed":false,"hand_anatomy_problem":false,'
    '"hand_product_intersection":false,"product_duplicate":false,"product_morph":false,"product_visible":true,"notes":"short"}')


def sample_frames(clip: str, out_dir: Path, count: int = 3, size: int = 640) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    r = subprocess.run([ffmpeg_exe(), "-i", clip], capture_output=True, text=True)
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr or "")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 3.0
    for k in range(count):
        t = dur * (k + 0.5) / count
        dst = out_dir / f"{Path(clip).stem}_f{k}.jpg"
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", clip, "-frames:v", "1",
                        "-vf", f"scale='min({size},iw)':-2", "-q:v", "3", str(dst)], capture_output=True)
        if dst.exists():
            frames.append(str(dst))
    return frames


def check(router, reference: str | None, clip: str, work_dir: Path, applicable: bool = True) -> dict:
    if not applicable:
        return {"status": "NOT_APPLICABLE", "reasons": ["상품이 나오지 않는 장면"]}
    if router is None or not router.has_real("vision") or not reference or not Path(reference).exists():
        return {"status": "UNVERIFIED", "reasons": ["원본과 비교할 Vision 평가를 쓸 수 없어요 - 이 장면은 사용하지 않아요"]}
    frames = sample_frames(clip, work_dir)
    if not frames:
        return {"status": "UNVERIFIED", "reasons": ["클립에서 프레임을 읽을 수 없어요"]}
    try:
        v = router.run("vision", "json", system=SYSTEM, user="Image 1 = REFERENCE product photo. Images 2+ = frames of the AI video.",
                       images=[reference] + frames, temperature=0).value
    except Exception as e:
        return {"status": "UNVERIFIED", "reasons": [f"Vision 호출 실패: {str(e)[:80]}"]}
    if not isinstance(v, dict):
        return {"status": "UNVERIFIED", "reasons": ["Vision 응답이 올바르지 않아요"]}
    bad = [k for k in CHECKS if v.get(k)]
    fid = int(v.get("fidelity", 0) or 0)
    if not v.get("product_visible", True):
        return {"status": "PRODUCT_MISMATCH", "fidelity": fid, "reasons": ["영상에서 상품이 보이지 않아요"], "notes": v.get("notes", "")}
    if not v.get("same_product", False) or fid < FIDELITY_MIN or bad:
        return {"status": "PRODUCT_MISMATCH", "fidelity": fid, "reasons": [f"{k}" for k in bad] or [f"fidelity {fid} < {FIDELITY_MIN}"],
                "notes": v.get("notes", "")}
    return {"status": "PASS", "fidelity": fid, "reasons": [], "notes": v.get("notes", "")}
