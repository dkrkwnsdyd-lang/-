"""Threads 동영상 게시 (Threads API).

Threads API 는 영상을 '공개 URL' 로만 받는다. config 의 general.public_base_url
(출력 폴더를 웹에 공개한 주소) 또는 threads.video_url 이 필요하다.
"""
from __future__ import annotations

from pathlib import Path

import requests

from .base import PostMeta, PublishError, Publisher, PublishResult, wait_until


class ThreadsPublisher(Publisher):
    name = "threads"

    def __init__(self, *args, session: requests.Session | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.http = session or requests.Session()
        self.base = self.config.get("api_base", "https://graph.threads.net/v1.0").rstrip("/")

    def _call(self, method: str, path: str, params: dict) -> dict:
        params = {**params, "access_token": self.config["access_token"]}
        resp = self.http.request(method, f"{self.base}/{path}", params=params, timeout=60)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in data:
            raise PublishError(f"Threads API 오류: {data.get('error', resp.text)}")
        return data

    def publish(self, video: Path, meta: PostMeta) -> PublishResult:
        self.require("access_token", "user_id")
        public_url = self.public_url_for(video)
        if not public_url:
            raise PublishError(
                "Threads 는 영상의 공개 URL 이 필요합니다. config.yaml 의 general.public_base_url 을 설정하세요.")
        uid = self.config["user_id"]
        container = self._call("POST", f"{uid}/threads", {
            "media_type": "VIDEO",
            "video_url": public_url,
            "text": meta.caption(500),
        })
        cid = container["id"]

        def ready() -> bool:
            st = self._call("GET", cid, {"fields": "status,error_message"})
            if st.get("status") in ("ERROR", "EXPIRED"):
                raise PublishError(f"Threads 영상 처리 실패: {st.get('error_message')}")
            return st.get("status") == "FINISHED"

        wait_until(ready, timeout=self.config.get("timeout", 600), interval=5, sleep=self.sleep)
        post = self._call("POST", f"{uid}/threads_publish", {"creation_id": cid})
        pid = post["id"]
        try:
            url = self._call("GET", pid, {"fields": "permalink"}).get("permalink")
        except PublishError:
            url = None
        return PublishResult(self.name, True, pid, url)
