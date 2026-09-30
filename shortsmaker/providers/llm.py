"""LLM / Vision provider: OpenAI, Google(Gemini), Groq.

모든 호출은 JSON 을 돌려받는다 (system 규칙과 job 데이터는 호출자가 분리해서 넘긴다).
"""
from __future__ import annotations

from pathlib import Path

from .base import Provider, ProviderError, ProviderResult, Usage, image_b64, parse_json, timed


class OpenAICompatible(Provider):
    base_url = "https://api.openai.com/v1"

    @timed
    def json(self, model: str, system: str, user: str, images: list[str | Path] | None = None,
             max_tokens: int = 3000, temperature: float | None = None) -> ProviderResult:
        content: list[dict] | str = user
        if images:
            content = [{"type": "text", "text": user}]
            for img in images:
                b64, mime = image_b64(img)
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        data = self.request_json("POST", f"{self.base_url}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {self.key}"})
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise ProviderError(f"{self.name}: 응답 형식 오류") from None
        u = data.get("usage", {})
        return ProviderResult(parse_json(text), self.name, model,
                              Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))

    def health_check(self) -> str:
        if not self.configured():
            return "not_configured"
        self.request_json("GET", f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.key}"})
        return "ok"


class OpenAIProvider(OpenAICompatible):
    name = "openai"
    env_key = "OPENAI_API_KEY"
    tasks = ("llm", "vision", "tts")

    @timed
    def tts(self, model: str, text: str, out: Path, voice: str = "alloy", speed: float = 1.0) -> ProviderResult:
        try:
            resp = self.http.post(f"{self.base_url}/audio/speech", timeout=120,
                                  headers={"Authorization": f"Bearer {self.key}"},
                                  json={"model": model, "input": text, "voice": voice,
                                        "response_format": "mp3", "speed": speed})
        except Exception as e:
            raise ProviderError(f"openai tts 연결 실패: {type(e).__name__}") from None
        if resp.status_code >= 400:
            raise ProviderError(f"openai tts HTTP {resp.status_code}")
        out.write_bytes(resp.content)
        return ProviderResult(out, self.name, model, Usage(len(text), 0))


class GroqProvider(OpenAICompatible):
    name = "groq"
    env_key = "GROQ_API_KEY"
    base_url = "https://api.groq.com/openai/v1"
    tasks = ("llm_cheap",)


class GoogleProvider(Provider):
    name = "google"
    env_key = "GEMINI_API_KEY"
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    tasks = ("llm", "vision", "video_understanding")
    probe_url = f"{base_url}/models?pageSize=1"

    @timed
    def json(self, model: str, system: str, user: str, images: list[str | Path] | None = None,
             video_url: str | None = None, max_tokens: int = 3000, temperature: float | None = None) -> ProviderResult:
        parts: list[dict] = []
        if video_url:  # 공개 YouTube URL 영상 이해
            parts.append({"file_data": {"file_uri": video_url}})
        for img in images or []:
            b64, mime = image_b64(img)
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        parts.append({"text": user})
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens},
        }
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        data = self.request_json("POST", f"{self.base_url}/models/{model}:generateContent", json=body,
                                 headers=self.auth_headers("x-goog-api-key"), timeout=300)
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise ProviderError("google: 응답 형식 오류") from None
        u = data.get("usageMetadata", {})
        return ProviderResult(parse_json(text), self.name, model,
                              Usage(u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)))

    def health_check(self) -> str:
        if not self.configured():
            return "not_configured"
        self.request_json("GET", f"{self.base_url}/models", headers=self.auth_headers("x-goog-api-key"))
        return "ok"
