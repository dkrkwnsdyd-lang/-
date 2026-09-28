from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class PostMeta:
    """플랫폼 공통 게시 정보. 각 플랫폼이 제한에 맞게 잘라서 쓴다."""
    title: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    privacy: str = "public"          # public | unlisted | private

    def tags_text(self, extra: list[str] | None = None) -> str:
        tags = []
        for t in [*self.hashtags, *(extra or [])]:
            t = t.strip().lstrip("#").replace(" ", "")
            if t and f"#{t}" not in tags:
                tags.append(f"#{t}")
        return " ".join(tags)

    def caption(self, limit: int, extra_tags: list[str] | None = None,
                include_title: bool = True) -> str:
        parts = [self.title if include_title else "", self.description, self.tags_text(extra_tags)]
        return truncate("\n\n".join(p for p in parts if p), limit)


@dataclass
class PublishResult:
    platform: str
    ok: bool
    post_id: str | None = None
    url: str | None = None
    error: str | None = None


class PublishError(RuntimeError):
    pass


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def wait_until(check: Callable[[], bool | None], timeout: float = 600, interval: float = 5,
               sleep: Callable[[float], None] = time.sleep) -> None:
    """check() 가 True 를 돌려줄 때까지 대기. 실패는 check 안에서 예외로 알린다."""
    deadline = time.monotonic() + timeout
    while True:
        if check():
            return
        if time.monotonic() > deadline:
            raise PublishError("플랫폼 처리 대기 시간 초과")
        sleep(interval)


class Publisher:
    name = "base"

    def __init__(self, config: dict, public_base_url: str | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config or {}
        self.public_base_url = public_base_url
        self.sleep = sleep

    def public_url_for(self, video: Path) -> str | None:
        """영상이 웹에 공개되어 있는 경우의 URL (쓰레드 등 URL 업로드만 되는 플랫폼용)."""
        if self.config.get("video_url"):
            return self.config["video_url"]
        if self.public_base_url:
            return self.public_base_url.rstrip("/") + "/" + video.name
        return None

    def require(self, *keys: str) -> None:
        missing = [k for k in keys if not self.config.get(k)]
        if missing:
            raise PublishError(f"{self.name} 설정이 필요합니다: {', '.join(missing)} (config.yaml 참고)")

    def publish(self, video: Path, meta: PostMeta) -> PublishResult:  # pragma: no cover
        raise NotImplementedError
