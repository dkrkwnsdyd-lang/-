"""입력 정리: 로컬 사진, 폴더, 이미지 URL, 유튜브 영상 URL(썸네일)을 이미지 파일 목록으로 바꾼다."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import requests

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

_YT_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def youtube_video_id(url: str) -> str | None:
    m = _YT_ID.search(url)
    return m.group(1) if m else None


def _download(url: str, dest: Path, session: requests.Session) -> bool:
    try:
        resp = session.get(url, timeout=30)
    except requests.RequestException:
        return False
    # 존재하지 않는 maxresdefault 는 404 또는 120x90 회색 이미지(작은 파일)를 준다
    if resp.status_code != 200 or len(resp.content) < 2000:
        return False
    dest.write_bytes(resp.content)
    return True


def resolve_inputs(inputs: list[str], workdir: Path | None = None,
                   session: requests.Session | None = None) -> list[Path]:
    """입력 목록을 순서를 유지한 채 이미지 파일 경로 목록으로 변환."""
    session = session or requests.Session()
    workdir = Path(workdir or tempfile.mkdtemp(prefix="shorts_src_"))
    workdir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []

    for idx, item in enumerate(inputs):
        if item.startswith(("http://", "https://")):
            vid = youtube_video_id(item)
            if vid:
                dest = workdir / f"{idx:03d}_{vid}.jpg"
                for name in ("maxresdefault", "sddefault", "hqdefault"):
                    if _download(f"https://i.ytimg.com/vi/{vid}/{name}.jpg", dest, session):
                        break
                else:
                    raise RuntimeError(f"유튜브 썸네일을 가져오지 못했습니다: {item}")
            else:
                suffix = Path(item.split("?")[0]).suffix.lower()
                dest = workdir / f"{idx:03d}{suffix if suffix in IMAGE_EXTS else '.jpg'}"
                if not _download(item, dest, session):
                    raise RuntimeError(f"이미지를 내려받지 못했습니다: {item}")
            result.append(dest)
            continue

        path = Path(item)
        if path.is_dir():
            result.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTS))
        elif path.is_file():
            result.append(path)
        else:
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {item}")

    if not result:
        raise ValueError("사진이 한 장도 없습니다.")
    return result
