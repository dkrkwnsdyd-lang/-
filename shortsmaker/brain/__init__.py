"""SHORTS BRAIN - 세 영역을 분리해서 관리한다.

SYSTEM RULES     : brain/system/*.yaml, brain/policy/*.yaml (사람이 관리, 코드와 함께 버전관리)
LEARNED KNOWLEDGE: data/brain/*.json (참고영상 분석/성과 데이터에서 쌓이는 지식, VERIFIED 만 반영)
CURRENT JOB DATA : studio.job.Job (작업마다 새로 만들어지고 규칙과 섞지 않는다)

하나의 거대한 프롬프트에 몰아넣지 않도록, 각 단계는 필요한 섹션만 꺼내 쓴다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BRAIN_DIR = Path(__file__).parent
DEFAULT_DATA_DIR = Path("data")


@lru_cache(maxsize=None)
def system(name: str) -> dict[str, Any]:
    """SYSTEM RULES 한 섹션 (예: system('hook_patterns'))."""
    with open(BRAIN_DIR / "system" / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=None)
def policy(name: str) -> dict[str, Any]:
    with open(BRAIN_DIR / "policy" / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class LearnedKnowledge:
    """참고 영상 패턴 / 성과 패턴 저장소. UNVERIFIED 는 학습에 반영하지 않는다."""

    SECTIONS = ("reference_patterns", "performance_patterns")

    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR):
        self.dir = Path(data_dir) / "brain"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, section: str) -> Path:
        if section not in self.SECTIONS:
            raise ValueError(section)
        return self.dir / f"{section}.json"

    def load(self, section: str) -> list[dict]:
        p = self._path(section)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def add(self, section: str, item: dict) -> bool:
        if item.get("status") == "UNVERIFIED":
            return False
        items = self.load(section)
        items.append(item)
        self._path(section).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
