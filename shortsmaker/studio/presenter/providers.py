"""VideoGenerationProvider 추상화 + Router. 처음에는 구조만: 실제 외부 호출 어댑터는 공식 문서로 검증된 뒤에 하나씩 추가한다.

- 검증되지 않은 provider(Higgsfield/Seedance/Kling)는 '자리'만 있고 호출하지 않는다 (엔드포인트/파라미터를 추측하지 않는다).
- Mock provider 는 테스트/화면 시연용으로만 쓰고(.env 의 SHORTSMAKER_MOCK_VIDEO=1 또는 코드에서 명시 주입) 결과에 mock=True 가 표시된다.
- 실패 시 다른 provider 로 무한 재시도하지 않는다: 요청당 최대 MAX_PROVIDER_TRIES 개 provider 만 시도.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_PROVIDER_TRIES = 2


class ProviderUnavailable(Exception):
    pass


@dataclass
class GenRequest:
    kind: str                      # AI_PRESENTER | AI_PRODUCT_UGC
    prompt: str
    seconds: float
    reference_image: str | None = None
    aspect: str = "9:16"
    settings: dict = field(default_factory=dict)


@dataclass
class GenResult:
    path: str
    seconds: float
    cost: float | None             # None = 비용 확인 불가
    provider: str
    model: str
    mock: bool = False
    meta: dict = field(default_factory=dict)


class VideoGenerationProvider:
    name = "base"
    model = ""
    env_key = ""
    verified = False               # 공식 문서/실제 호출로 검증됐는가
    mock = False
    capabilities: tuple = ()       # 'talking_head', 'product_hold', 'image_to_video' ... (공급자 주장, 검증 전)
    quality = 3                    # 1~5 (선택 우선순위용 대략값, 검증 전)
    speed = 3
    price_per_second: float | None = None      # USD. 공식 가격을 확인하기 전에는 None

    def configured(self) -> bool:
        return bool(os.environ.get(self.env_key)) if self.env_key else True

    def available(self) -> bool:
        return self.verified and self.configured()

    def generate(self, req: GenRequest, out: Path) -> GenResult:
        raise ProviderUnavailable(f"{self.name}: 어댑터가 검증되지 않아 호출하지 않아요")


class _Unverified(VideoGenerationProvider):
    verified = False


class HiggsfieldProvider(_Unverified):
    name, env_key, capabilities, quality, speed = "higgsfield", "HIGGSFIELD_API_KEY", ("image_to_video", "cinematic_camera"), 5, 2


class SeedanceProvider(_Unverified):
    name, env_key, capabilities, quality, speed = "seedance", "SEEDANCE_API_KEY", ("image_to_video", "product_hold", "reference_image"), 4, 3


class KlingProvider(_Unverified):
    name, env_key, capabilities, quality, speed = "kling", "KLING_API_KEY", ("image_to_video", "talking_head", "product_hold"), 4, 3


class MockVideoProvider(VideoGenerationProvider):
    """실제 AI 가 아니다: 기준 이미지를 천천히 확대한 영상 + 'MOCK' 표시. 흐름(Preview/비용/캐시/폴백) 검증 전용."""
    name, model, verified, mock = "mock", "mock-zoom", True, True
    capabilities = ("talking_head", "product_hold", "image_to_video")
    price_per_second = 0.0

    def configured(self) -> bool:
        return True

    def generate(self, req: GenRequest, out: Path) -> GenResult:
        from ...video import ffmpeg_exe
        if not req.reference_image or not Path(req.reference_image).exists():
            raise ProviderUnavailable("mock: 기준 이미지 필요")
        out.parent.mkdir(parents=True, exist_ok=True)
        fps, n = 24, int(req.seconds * 24)
        vf = (f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
              f"zoompan=z='1+0.0015*on':d={n}:s=540x960:fps={fps},drawbox=x=0:y=0:w=iw:h=40:color=black@0.6:t=fill")
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-loop", "1", "-i", req.reference_image, "-t", f"{req.seconds:.2f}",
               "-vf", vf, "-r", str(fps), "-pix_fmt", "yuv420p", "-an", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            raise ProviderUnavailable("mock: 영상 생성 실패 " + (r.stderr or "")[-120:])
        return GenResult(str(out), req.seconds, 0.0, self.name, self.model, mock=True)


def default_providers() -> list[VideoGenerationProvider]:
    ps: list[VideoGenerationProvider] = [HiggsfieldProvider(), SeedanceProvider(), KlingProvider()]
    if os.environ.get("SHORTSMAKER_MOCK_VIDEO") == "1":
        ps.append(MockVideoProvider())
    return ps


def rank(providers: list[VideoGenerationProvider], kind: str, cost_mode: str) -> list[VideoGenerationProvider]:
    """kind/cost_mode 에 맞는 순서. AI_PRESENTER=talking_head 가능한 곳 우선, AI_PRODUCT_UGC=product_hold 우선,
    PREMIUM=품질, 그 외=가격(알려진 값)·속도. 사용할 수 없는(미검증/키 없음) provider 는 제외."""
    cap = "talking_head" if kind == "AI_PRESENTER" else "product_hold"
    ok = [p for p in providers if p.available()]

    def key(p):
        price = p.price_per_second if p.price_per_second is not None else 9.9
        base = (0 if cap in p.capabilities else 1)
        return (base, -p.quality, price) if cost_mode == "PREMIUM" else (base, price, -p.speed, -p.quality)
    return sorted(ok, key=key)
