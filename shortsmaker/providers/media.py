"""TTS / B-roll / 영상 생성 provider."""
from __future__ import annotations

from pathlib import Path

from .base import NotConfigured, Provider, ProviderError, ProviderResult, Usage, timed


class ElevenLabsProvider(Provider):
    name = "elevenlabs"
    env_key = "ELEVENLABS_API_KEY"
    tasks = ("tts",)
    base_url = "https://api.elevenlabs.io/v1"

    @timed
    def tts(self, model: str, text: str, out: Path, voice: str | None = None, speed: float = 1.0) -> ProviderResult:
        import os
        voice = voice or os.environ.get("ELEVENLABS_VOICE_ID")
        if not voice:
            raise NotConfigured("elevenlabs: ELEVENLABS_VOICE_ID 필요")
        try:
            resp = self.http.post(f"{self.base_url}/text-to-speech/{voice}", timeout=120,
                                  headers={"xi-api-key": self.key, "Accept": "audio/mpeg"},
                                  json={"text": text, "model_id": model,
                                        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8,
                                                           "speed": speed}})
        except Exception as e:
            raise ProviderError(f"elevenlabs 연결 실패: {type(e).__name__}") from None
        if resp.status_code >= 400:
            raise ProviderError(f"elevenlabs HTTP {resp.status_code}")
        out.write_bytes(resp.content)
        return ProviderResult(out, self.name, model, Usage(len(text), 0))

    def health_check(self) -> str:
        if not self.configured():
            return "not_configured"
        self.request_json("GET", f"{self.base_url}/models", headers={"xi-api-key": self.key})
        return "ok"


class PexelsProvider(Provider):
    name = "pexels"
    env_key = "PEXELS_API_KEY"
    tasks = ("broll",)

    @timed
    def search(self, model: str, query: str, per_page: int = 5) -> ProviderResult:
        data = self.request_json("GET", "https://api.pexels.com/videos/search",
                                 params={"query": query, "per_page": per_page, "orientation": "portrait"},
                                 headers={"Authorization": self.key})
        items = [{"url": v["url"], "files": v.get("video_files", []), "rights": "STOCK_LICENSED",
                  "source": "pexels"} for v in data.get("videos", [])]
        return ProviderResult(items, self.name, model)


class PixabayProvider(Provider):
    name = "pixabay"
    env_key = "PIXABAY_API_KEY"
    tasks = ("broll",)

    @timed
    def search(self, model: str, query: str, per_page: int = 5) -> ProviderResult:
        data = self.request_json("GET", "https://pixabay.com/api/videos/",
                                 params={"key": self.key, "q": query, "per_page": max(3, per_page)})
        items = [{"url": h["pageURL"], "files": h.get("videos", {}), "rights": "STOCK_LICENSED",
                  "source": "pixabay"} for h in data.get("hits", [])]
        return ProviderResult(items, self.name, model)


class UnverifiedVideoProvider(Provider):
    """요청 형식을 공식 문서로 검증하기 전까지 호출하지 않는 영상 생성 provider 자리.

    capability 만 선언하고, generate() 는 명시적으로 실패시켜 라우터가 폴백하게 한다.
    (추측으로 만든 endpoint 로 유료 API 를 호출하지 않기 위함)
    """
    tasks = ("video",)
    paid_generation = True

    def generate(self, model: str, **kwargs) -> ProviderResult:
        raise ProviderError(f"{self.name}: 영상 생성 adapter 미검증 - API 문서 확인 후 구현 필요")

    def health_check(self) -> str:
        return "configured_unverified" if self.configured() else "not_configured"


class SeedanceProvider(UnverifiedVideoProvider):
    name = "seedance"
    env_key = "SEEDANCE_API_KEY"


class HiggsfieldProvider(UnverifiedVideoProvider):
    name = "higgsfield"
    env_key = "HIGGSFIELD_API_KEY"


class GoogleVideoProvider(UnverifiedVideoProvider):
    name = "google_video"
    env_key = "GEMINI_API_KEY"
