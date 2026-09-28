from __future__ import annotations

from pathlib import Path

from .base import PostMeta, PublishError, Publisher, PublishResult
from .instagram import InstagramPublisher
from .threads import ThreadsPublisher
from .tiktok import TikTokPublisher
from .youtube import YouTubePublisher

PUBLISHERS: dict[str, type[Publisher]] = {
    "youtube": YouTubePublisher,
    "instagram": InstagramPublisher,
    "threads": ThreadsPublisher,
    "tiktok": TikTokPublisher,
}

PLATFORM_LABELS = {
    "youtube": "유튜브 쇼츠",
    "instagram": "인스타그램 릴스",
    "threads": "쓰레드",
    "tiktok": "틱톡",
}


def publish_all(video: str | Path, meta: PostMeta, platforms: list[str], config: dict) -> list[PublishResult]:
    """여러 플랫폼에 순서대로 게시. 한 곳이 실패해도 나머지는 계속한다."""
    video = Path(video)
    public_base = (config.get("general") or {}).get("public_base_url")
    results = []
    for name in platforms:
        cls = PUBLISHERS.get(name)
        if cls is None:
            results.append(PublishResult(name, False, error=f"지원하지 않는 플랫폼: {name}"))
            continue
        try:
            publisher = cls(config.get(name) or {}, public_base_url=public_base)
            results.append(publisher.publish(video, meta))
        except Exception as e:  # 플랫폼별 오류를 결과로 모아 보여준다
            results.append(PublishResult(name, False, error=str(e)))
    return results


__all__ = ["PostMeta", "PublishError", "Publisher", "PublishResult", "PUBLISHERS",
           "PLATFORM_LABELS", "publish_all"]
