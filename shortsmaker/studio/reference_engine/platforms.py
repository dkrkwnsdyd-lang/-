from __future__ import annotations

import re
from pathlib import Path

from ..reference import classify_reference_url

_RX = [("youtube_shorts", r"(?:youtube\.com/(?:shorts/|watch\?)|youtu\.be/)"), ("instagram_reels", r"instagram\.com/(?:reel|reels|p)/"),
       ("xiaohongshu", r"(?:xiaohongshu\.com/(?:explore|discovery/item)/|xhslink\.com/|rednote\.com/)"), ("tiktok", r"tiktok\.com/")]


def detect_platform(ref: str) -> str:
    if ref and Path(ref).exists():
        return "upload"
    for name, rx in _RX:
        if re.search(rx, ref or "", re.I):
            return name
    return "other"


def usable_url(ref: str) -> tuple[bool, str]:
    """검색/탐색 페이지는 영상 하나가 아니다."""
    kind = classify_reference_url(ref)
    if kind == "SEARCH_RESULT":
        return False, "개별 영상 링크가 필요해요 (검색결과/탐색 페이지는 분석하지 않아요)"
    return True, ""
