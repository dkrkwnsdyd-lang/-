"""복제 방지: 참고 영상의 말/자막 원문을 저장하지 않고, 원문을 복원할 수 없는 '4자 조각 해시'만 남겨서 나중에 새 대본이 원문과 겹치는지 검사한다."""
from __future__ import annotations

import hashlib
import re

SHINGLE = 4
MAX_HASHES = 600
COPY_THRESHOLD = 0.25          # 새 문장의 조각 중 25% 이상이 참고 영상 조각이면 복제 위험
MIN_LEN = 8                    # 너무 짧은 문장은 우연히 겹치므로 검사하지 않는다


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def shingles(text: str) -> set[str]:
    t = _norm(text)
    return {hashlib.sha1(t[i:i + SHINGLE].encode()).hexdigest()[:10] for i in range(max(0, len(t) - SHINGLE + 1))}


def make(texts: list[str]) -> list[str]:
    """원문 목록 → 해시 목록 (원문은 반환/저장하지 않는다)."""
    hs: set[str] = set()
    for t in texts:
        hs |= shingles(t)
    return sorted(hs)[:MAX_HASHES]


def overlap(text: str, fp: list[str] | set[str] | None) -> float:
    if not fp or len(_norm(text)) < MIN_LEN:
        return 0.0
    s = shingles(text)
    return len(s & set(fp)) / len(s) if s else 0.0
