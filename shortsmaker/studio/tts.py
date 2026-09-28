"""TTS - provider 가 있으면 장면별 음성 생성, 없으면 None (자막+음악 버전으로 진행)."""
from __future__ import annotations

from pathlib import Path

from .. import brain
from .audio import audio_duration


def synthesize(router, scenes, out_dir: Path) -> dict[str, tuple[float, str]]:
    if router is None or not router.has_real("tts"):
        return {}
    rules = brain.system("tts_rules")
    out_dir.mkdir(parents=True, exist_ok=True)
    voice = {}
    for s in scenes:
        text = s.tts_line.strip()
        if not text:
            continue
        path = out_dir / f"{s.scene_id}.mp3"
        router.run("tts", "tts", text=text, out=path, speed=rules["speed"])
        voice[s.scene_id] = (round(audio_duration(path), 3), str(path))
    return voice
