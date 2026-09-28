"""YouTube Shorts 업로드 (YouTube Data API v3).

세로 영상 + 3분 이하면 자동으로 쇼츠로 분류된다. 제목/설명에 #Shorts 를 붙여 준다.
최초 1회 브라우저 로그인(OAuth) 후 토큰 파일이 저장된다.
"""
from __future__ import annotations

from pathlib import Path

from .base import PostMeta, PublishError, Publisher, PublishResult, truncate

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_credentials(client_secrets_file: str, token_file: str, interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not interactive:
            raise PublishError("YouTube 로그인이 필요합니다: python -m shortsmaker youtube-auth")
        if not Path(client_secrets_file).exists():
            raise PublishError(f"OAuth 클라이언트 파일이 없습니다: {client_secrets_file}")
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
        creds = flow.run_local_server(port=0)
    Path(token_file).write_text(creds.to_json(), encoding="utf-8")
    return creds


class YouTubePublisher(Publisher):
    name = "youtube"

    def publish(self, video: Path, meta: PostMeta) -> PublishResult:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds = get_credentials(
            self.config.get("client_secrets_file", "client_secret.json"),
            self.config.get("token_file", "youtube_token.json"),
            interactive=self.config.get("interactive_login", False),
        )
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

        title = meta.title if "#shorts" in meta.title.lower() else f"{meta.title} #Shorts"
        body = {
            "snippet": {
                "title": truncate(title, 100),
                "description": truncate(meta.caption(5000, extra_tags=["Shorts"], include_title=False), 5000),
                "tags": [t.lstrip("#") for t in meta.hashtags][:30],
                "categoryId": str(self.config.get("category_id", "22")),
            },
            "status": {
                "privacyStatus": meta.privacy if meta.privacy in ("public", "unlisted", "private") else "public",
                "selfDeclaredMadeForKids": bool(self.config.get("made_for_kids", False)),
            },
        }
        media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        vid = response["id"]
        return PublishResult(self.name, True, vid, f"https://youtube.com/shorts/{vid}")
