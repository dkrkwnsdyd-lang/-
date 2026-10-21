"""SHOP SHORTS AI V2 -> Hypit Agent handoff.

This bridge intentionally does NOT call a paid model, download reference videos,
or execute Hypit.  It exports an allowlisted production brief for Claude Code/Codex
to turn into an editable Hypit project.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
_SCENE_FIELDS = (
    "scene_id", "beat", "duration", "purpose", "subject", "action",
    "shot", "caption", "tts_line", "camera_motion", "transition",
    "reference_image", "continuity_rules",
)


def _find_local_media(raw: str, result_file: Path) -> Path | None:
    """Look for an existing local image. Never fetch URLs or remote paths."""
    if not isinstance(raw, str) or not raw or "://" in raw:
        return None
    p = Path(raw).expanduser()
    candidates = [p] if p.is_absolute() else [
        Path.cwd() / p, result_file.parent / p, result_file.parent.parent / p,
    ]
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in _MEDIA_SUFFIXES:
            return candidate.resolve()
    return None


def prepare_hypit(result_path: str | Path, output_dir: str | Path | None = None,
                  copy_images: bool = True) -> Path:
    """Create a private, local Hypit handoff directory from a V2 result.json.

    Returns the created brief path.  No publishing, model requests, or Hypit
    execution happens here. Quality/compliance approvals are never inherited.
    """
    result_file = Path(result_path).expanduser().resolve()
    data = json.loads(result_file.read_text(encoding="utf-8"))
    if data.get("status") in ("FAILED", "STRATEGY_BLOCKED"):
        raise ValueError("실패/전략 차단된 작업은 Hypit으로 넘길 수 없습니다.")
    plan = data.get("plan") or {}
    scenes = plan.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("result.json에 장면 계획(plan.scenes)이 없습니다.")

    root = (Path(output_dir).expanduser() if output_dir else result_file.parent / "hypit").resolve()
    root.mkdir(parents=True, exist_ok=True)
    asset_dir = root / "assets"
    identity = data.get("identity") or {}
    photos = identity.get("photos") or []
    copied: dict[str, str] = {}
    missing = []
    if copy_images:
        asset_dir.mkdir(exist_ok=True)
    for index, photo in enumerate(photos):
        raw = photo.get("path") if isinstance(photo, dict) else None
        if not raw or not isinstance(raw, str):
            continue
        found = _find_local_media(raw, result_file)
        if not found:
            missing.append(raw)
            continue
        if copy_images:
            dest = asset_dir / f"product_{index + 1:02d}{found.suffix.lower()}"
            shutil.copy2(found, dest)
            copied[raw] = (Path("assets") / dest.name).as_posix()
        else:
            copied[raw] = str(found)

    safe_scenes = []
    for s in scenes:
        if not isinstance(s, dict):
            continue
        row = {k: s[k] for k in _SCENE_FIELDS if k in s}
        image = row.get("reference_image")
        if image:
            row["reference_image"] = copied.get(image)
        safe_scenes.append(row)

    reference = data.get("reference") or {}
    compliance = data.get("compliance") or {}
    qa = data.get("qa") or {}
    manifest = {
        "source": "SHOP SHORTS AI V2",
        "job_id": data.get("job_id"),
        "original_status": data.get("status"),
        "product": {
            "name": identity.get("name") or "확인 필요",
            "distinctive_features": identity.get("distinctive_features") or [],
            "colors": identity.get("color_reference") or [],
            "identity_lock": "사진의 색상, 로고, 부품, 비율, 버튼 위치를 바꾸지 말 것",
        },
        "video": {
            "aspect_ratio": "9:16",
            "language": "ko-KR",
            "duration_seconds": round(sum(float(s.get("duration") or 0) for s in safe_scenes), 2),
            "story_pattern": plan.get("story_pattern"),
            "scenes": safe_scenes,
        },
        "reference": {
            "source": reference.get("source"),
            "verification": reference.get("status", "UNVERIFIED"),
            "structure_only": True,
        },
        "quality": {
            "verdict": qa.get("verdict") or data.get("status"),
            "overall": (qa.get("scores") or {}).get("overall"),
            "must_retest": True,
        },
        "compliance": {
            "must_retest": True,
            "existing_platform_verdicts": {
                name: item.get("verdict") for name, item in
                (compliance.get("platforms") or {}).items() if isinstance(item, dict)
            },
        },
        "assets": list(copied.values()),
        "missing_images": missing,
    }
    manifest_file = root / "shop_shorts_manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    brief = (
        "# SHOP SHORTS AI → Hypit 제작 전달서\n\n"
        "이 폴더는 Hypit Agent에 넘길 준비물입니다. MP4나 SVML 생성이 완료된 상태는 아닙니다.\n\n"
        "## Claude Code / Codex 작업 지시\n\n"
        "1. Hypit Skill의 최신 문서를 확인하고 Hypit 실행 환경을 점검하세요.\n"
        "2. shop_shorts_manifest.json의 장면, 상품 고정 규칙, 이용 가능한 assets를 기반으로 "
        "한국어 9:16 쇼핑 숏폼용 편집 가능한 .svml/.svrun 프로젝트를 작성하세요.\n"
        "3. 참고 영상은 추상적인 훅/편집 리듬만 연구하세요. 원본 문장, 화면 배열, "
        "인물 얼굴/목소리, 타인 영상을 허락 없이 복제하지 마세요.\n"
        "4. 사진·입력 자료에 없는 후기, 판매량, 할인, 성능, 효능, 사용 경험을 "
        "사실로 만들지 마세요. 원본 제품의 형상·색상·로고를 유지하세요.\n"
        "5. 우선 생성 모델 없는 로컬 렌더 가능한 버전을 제안하세요. "
        "유료 API 호출 전에 공급자·가격·예산을 명시하고 승인을 받으세요.\n"
        "6. 기존 SHOP SHORTS AI 결과의 QA/컴플라이언스를 재사용하지 말고 "
        "새 렌더에 대해 품질 검사와 제휴 광고 고지·권리 검사를 다시 수행하세요.\n"
        "7. 결과물을 이 폴더에 저장하고 기존 파이프라인·기존 master.mp4는 수정하지 마세요.\n\n"
        "## 실행 가이드\n\n"
        "- Skill 설치(1회): npx skills add hypit-ai/hypit -g\n"
        "- Hypit 실행기 확인: hypit version --check\n"
        "- Coding Agent에: /hypit 이 폴더의 SHOP_SHORTS_HYPIT_BRIEF.md와 "
        "shop_shorts_manifest.json을 읽고 편집 가능한 영상 프로젝트를 만들어줘.\n"
        "- Hypit 프로젝트 파일이 준비되면: hypit plan <파일.svrun> 이후, "
        "승인된 비용/범위에서 hypit build <파일.svrun> --follow\n\n"
        f"기존 작업 상태: {data.get('status', 'UNKNOWN')}. "
        "QUALITY_FAIL/NEEDS_REVIEW는 게시 가능 판정이 아닙니다.\n"
        f"복사한 사진: {len(copied)}개 / 누락된 사진: {len(missing)}개\n"
    )
    brief_file = root / "SHOP_SHORTS_HYPIT_BRIEF.md"
    brief_file.write_text(brief, encoding="utf-8")
    return brief_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SHOP SHORTS AI result.json -> Hypit Agent 준비 파일")
    parser.add_argument("result_json", help="output/v2/<job_id>/result.json")
    parser.add_argument("--out", help="준비 폴더 (기본: 해당 작업 폴더/hypit)")
    parser.add_argument("--no-copy", action="store_true", help="사진 복사 없이 원래 경로 참조")
    args = parser.parse_args(argv)
    try:
        brief = prepare_hypit(args.result_json, args.out, copy_images=not args.no_copy)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Hypit 준비 실패: {exc}\n")
    print(f"Hypit 준비 완료: {brief}")
    print("실제 Hypit 렌더/유료 API 호출은 하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
