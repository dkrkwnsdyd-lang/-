"""TikTok 업로드 (Content Posting API, Direct Post + FILE_UPLOAD).

심사(audit) 전 앱은 비공개(SELF_ONLY)로만 게시된다.
"""
from __future__ import annotations

from pathlib import Path

import requests

from .base import PostMeta, PublishError, Publisher, PublishResult, wait_until

API = "https://open.tiktokapis.com/v2"
MIN_CHUNK = 5 * 1024 * 1024
MAX_SINGLE = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024

PRIVACY_MAP = {"public": "PUBLIC_TO_EVERYONE", "unlisted": "MUTUAL_FOLLOW_FRIENDS", "private": "SELF_ONLY"}


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) - 마지막 청크가 나머지를 흡수한다."""
    if size <= MAX_SINGLE:
        return size, 1
    return CHUNK, size // CHUNK


class TikTokPublisher(Publisher):
    name = "tiktok"

    def __init__(self, *args, session: requests.Session | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.http = session or requests.Session()

    def _post(self, path: str, body: dict) -> dict:
        resp = self.http.post(f"{API}/{path}", json=body, timeout=60, headers={
            "Authorization": f"Bearer {self.config['access_token']}",
            "Content-Type": "application/json; charset=UTF-8",
        })
        data = resp.json() if resp.content else {}
        err = data.get("error", {})
        if resp.status_code >= 400 or (err.get("code") not in (None, "ok")):
            raise PublishError(f"TikTok API 오류: {err or resp.text}")
        return data.get("data", {})

    def publish(self, video: Path, meta: PostMeta) -> PublishResult:
        self.require("access_token")
        size = video.stat().st_size
        chunk_size, count = chunk_plan(size)
        privacy = self.config.get("privacy_level") or PRIVACY_MAP.get(meta.privacy, "SELF_ONLY")
        init = self._post("post/publish/video/init/", {
            "post_info": {
                "title": meta.caption(2200),
                "privacy_level": privacy,
                "disable_comment": False,
                "disable_duet": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": count,
            },
        })
        publish_id, upload_url = init["publish_id"], init["upload_url"]

        with open(video, "rb") as f:
            for i in range(count):
                start = i * chunk_size
                end = size - 1 if i == count - 1 else start + chunk_size - 1
                f.seek(start)
                chunk = f.read(end - start + 1)
                resp = self.http.put(upload_url, data=chunk, timeout=600, headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                })
                if resp.status_code >= 400:
                    raise PublishError(f"TikTok 업로드 실패 ({i + 1}/{count}): {resp.text}")

        def ready() -> bool:
            st = self._post("post/publish/status/fetch/", {"publish_id": publish_id})
            status = st.get("status")
            if status == "FAILED":
                raise PublishError(f"TikTok 게시 실패: {st.get('fail_reason')}")
            return status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX")

        wait_until(ready, timeout=self.config.get("timeout", 600), interval=5, sleep=self.sleep)
        return PublishResult(self.name, True, publish_id, None)
