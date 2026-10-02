"""AI 클립 캐시: 같은 (상품 이미지 + 프롬프트 + provider + 모델 + 설정)이면 다시 호출하지 않는다.

실패한 결과(상품 불일치 등)도 meta 에 기록해서, 같은 입력으로 또 돈을 쓰지 않는다 (명시적 재생성만 예외).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

CACHE_DIR = Path("data/ai_clips")


def file_sha(path: str | None) -> str:
    if not path or not Path(path).exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def key_for(provider: str, model: str, kind: str, prompt: str, image_sha: str, seconds: float, settings: dict | None = None) -> str:
    raw = json.dumps({"p": provider, "m": model, "k": kind, "t": prompt, "i": image_sha, "s": round(seconds, 2), "x": settings or {}},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def lookup(key: str, cache_dir: Path | None = None) -> dict | None:
    d = Path(cache_dir or CACHE_DIR)
    meta = d / f"{key}.json"
    clip = d / f"{key}.mp4"
    if not meta.exists() or not clip.exists():
        return None
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except ValueError:
        return None
    m["path"] = str(clip)
    return m


def store(key: str, produced: str, meta: dict, cache_dir: Path | None = None) -> str:
    d = Path(cache_dir or CACHE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    clip = d / f"{key}.mp4"
    if Path(produced).resolve() != clip.resolve():
        shutil.copy(produced, clip)
    (d / f"{key}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(clip)


def update_meta(key: str, patch: dict, cache_dir: Path | None = None) -> None:
    d = Path(cache_dir or CACHE_DIR)
    meta = d / f"{key}.json"
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    m.update(patch)
    meta.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
