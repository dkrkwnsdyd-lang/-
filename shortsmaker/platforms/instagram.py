"""Instagram Reels 업로드 (Instagram Graph API).

필요: 프로페셔널(비즈니스/크리에이터) 계정, access_token, user_id(IG 사용자 ID).
영상 공개 URL 이 없으면 resumable 업로드로 로컬 파일을 직접 올린다.
"""
from __future__ import annotations

from pathlib import Path

import requests

from .base import PostMeta, PublishError, Publisher, PublishResult, wait_until


class InstagramPublisher(Publisher):
    name = "instagram"

    def __init__(self, *args, session: requests.Session | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.http = session or requests.Session()
        host = self.config.get("graph_host", "https://graph.facebook.com")
        self.base = f"{host.rstrip('/')}/{self.config.get('api_version', 'v21.0')}"

    def _call(self, method: str, path: str, **kwargs) -> dict:
        params = kwargs.pop("params", {})
        params["access_token"] = self.config["access_token"]
        resp = self.http.request(method, f"{self.base}/{path}", params=params, timeout=60, **kwargs)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "error" in data:
            raise PublishError(f"Instagram API 오류: {data.get('error', resp.text)}")
        return data

    def publish(self, video: Path, meta: PostMeta) -> PublishResult:
        self.require("access_token", "user_id")
        uid = self.config["user_id"]
        params = {
            "media_type": "REELS",
            "caption": meta.caption(2200),
            "share_to_feed": "true",
        }
        public_url = self.public_url_for(video)
        if public_url:
            params["video_url"] = public_url
        else:
            params["upload_type"] = "resumable"
        container = self._call("POST", f"{uid}/media", params=params)
        cid = container["id"]

        if not public_url:
            size = video.stat().st_size
            upload_uri = container.get("uri") or \
                f"https://rupload.facebook.com/ig-api-upload/{self.config.get('api_version', 'v21.0')}/{cid}"
            with open(video, "rb") as f:
                resp = self.http.post(upload_uri, data=f, timeout=600, headers={
                    "Authorization": f"OAuth {self.config['access_token']}",
                    "offset": "0",
                    "file_size": str(size),
                })
            if resp.status_code >= 400:
                raise PublishError(f"Instagram 영상 업로드 실패: {resp.text}")

        def ready() -> bool:
            st = self._call("GET", cid, params={"fields": "status_code,status"})
            code = st.get("status_code")
            if code in ("ERROR", "EXPIRED"):
                raise PublishError(f"Instagram 영상 처리 실패: {st.get('status')}")
            return code == "FINISHED"

        wait_until(ready, timeout=self.config.get("timeout", 600), interval=5, sleep=self.sleep)
        media = self._call("POST", f"{uid}/media_publish", params={"creation_id": cid})
        mid = media["id"]
        try:
            url = self._call("GET", mid, params={"fields": "permalink"}).get("permalink")
        except PublishError:
            url = None
        return PublishResult(self.name, True, mid, url)
