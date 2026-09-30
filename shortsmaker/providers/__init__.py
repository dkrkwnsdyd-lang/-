"""Provider 추상화 + MODEL REGISTRY + 라우터 (재시도/폴백/비용/상태 기록).

외부 API 는 반드시 Router 를 거쳐 호출한다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .base import NotConfigured, Provider, ProviderError, ProviderResult, mask, scrub
from .llm import GoogleProvider, GroqProvider, OpenAIProvider
from .media import (ElevenLabsProvider, GoogleVideoProvider, HiggsfieldProvider, PexelsProvider,
                    PixabayProvider, SeedanceProvider)

REGISTRY_FILE = Path(__file__).parent / "model_registry.yaml"

PROVIDER_CLASSES: dict[str, type[Provider]] = {
    c.name: c for c in (OpenAIProvider, GoogleProvider, GroqProvider, ElevenLabsProvider, PexelsProvider,
                        PixabayProvider, SeedanceProvider, HiggsfieldProvider, GoogleVideoProvider)
}


@dataclass
class ModelEntry:
    provider: str
    task: str
    model: str
    priority: int
    enabled: bool
    cost_level: int
    quality_level: int
    capabilities: list[str]
    fallback_model: str | None = None
    last_verified: str | None = None
    cost_per_1k_in: float = 0.0
    cost_per_1k_out: float = 0.0
    cost_per_1k_chars: float = 0.0

    def cost(self, inp: float, out: float) -> float:
        if self.cost_per_1k_chars:
            return inp / 1000 * self.cost_per_1k_chars
        return inp / 1000 * self.cost_per_1k_in + out / 1000 * self.cost_per_1k_out


def load_registry(path: Path = REGISTRY_FILE) -> list[ModelEntry]:
    with open(path, encoding="utf-8") as f:
        rows = yaml.safe_load(f) or []
    fields = ModelEntry.__dataclass_fields__
    return [ModelEntry(**{k: v for k, v in r.items() if k in fields}) for r in rows]


class Router:
    """task 별로 우선순위대로 provider 를 시도하고 실패하면 다음으로 넘어간다.

    local 항목은 호출자가 넘긴 local_fn 으로 처리한다 (항상 마지막 폴백).
    """

    def __init__(self, db=None, job_id: str | None = None, providers: dict[str, Provider] | None = None,
                 registry: list[ModelEntry] | None = None, status_file: str | Path = "data/api_status.json",
                 max_attempts: int = 2, sleep: Callable[[float], None] = time.sleep):
        self.db, self.job_id = db, job_id
        self.registry = registry if registry is not None else load_registry()
        self.providers = providers if providers is not None else {n: c() for n, c in PROVIDER_CLASSES.items()}
        self.status_file = Path(status_file)
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.trace: list[dict] = []
        self.dead: set[str] = set()      # 이 작업 동안 결제(402)/인증(401) 오류가 난 provider - 다시 시도하지 않는다

    # ------------------------------------------------------------ status
    def _status(self) -> dict:
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _record(self, provider: str, ok: bool, latency: float = 0, error: str = "") -> None:
        st = self._status()
        s = st.setdefault(provider, {})
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            s.update(last_success=now, latency=round(latency, 2))
        else:
            s.update(last_error=scrub(error)[:300], last_error_at=now)
        try:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            self.status_file.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ routing
    def candidates(self, task: str, need: list[str] | None = None) -> list[ModelEntry]:
        rows = [m for m in self.registry if m.task == task and m.enabled
                and all(c in m.capabilities for c in (need or []))]
        rows.sort(key=lambda m: m.priority)
        rows = [m for m in rows if m.provider not in self.dead]
        return [m for m in rows if m.provider == "local"
                or (m.provider in self.providers and self.providers[m.provider].configured())]

    def run(self, task: str, method: str, local_fn: Callable[[], Any] | None = None,
            need: list[str] | None = None, **kwargs) -> ProviderResult:
        errors = []
        for entry in self.candidates(task, need):
            if entry.provider == "local":
                if local_fn is None:
                    continue
                t = time.monotonic()
                value = local_fn()
                self.trace.append({"task": task, "provider": "local", "model": entry.model, "ok": True})
                self._log_cost(entry, 0, 0, time.monotonic() - t)
                return ProviderResult(value, "local", entry.model)
            prov = self.providers[entry.provider]
            for attempt in range(self.max_attempts):
                try:
                    res: ProviderResult = getattr(prov, method)(entry.model, **kwargs)
                    res.usage.estimated_cost = entry.cost(res.usage.input_units, res.usage.output_units)
                    self._record(entry.provider, True, res.latency)
                    self._log_cost(entry, res.usage.input_units, res.usage.output_units, res.latency,
                                   res.usage.estimated_cost)
                    self.trace.append({"task": task, "provider": entry.provider, "model": entry.model, "ok": True})
                    return res
                except NotConfigured as e:
                    errors.append(str(e))
                    break
                except ProviderError as e:
                    errors.append(str(e))
                    self._record(entry.provider, False, error=str(e))
                    self.trace.append({"task": task, "provider": entry.provider, "model": entry.model,
                                       "ok": False, "error": scrub(str(e))[:200]})
                    if not e.retryable:
                        if e.status in (401, 402):
                            self.dead.add(entry.provider)
                        break
                    if attempt + 1 < self.max_attempts:
                        self.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"{task}: 사용 가능한 provider 가 없습니다. " + " | ".join(errors[-3:]))

    def _log_cost(self, entry: ModelEntry, inp: float, out: float, dur: float, cost: float = 0.0) -> None:
        if self.db is not None:
            self.db.add_cost(self.job_id, entry.provider, entry.model, entry.task, inp, out, cost, dur)

    def has_real(self, task: str) -> bool:
        return any(m.provider != "local" for m in self.candidates(task))

    # ------------------------------------------------------------ control center
    def control_center(self, test: bool = False) -> list[dict]:
        st = self._status()
        out = []
        for name, prov in self.providers.items():
            entries = [m for m in self.registry if m.provider == name]
            active = next((m for m in sorted(entries, key=lambda m: m.priority) if m.enabled), None)
            row = {
                "provider": name,
                "authentication": prov.auth_state(),
                "active_model": active.model if active else None,
                "tasks": sorted({m.task for m in entries}),
                "capabilities": sorted({c for m in entries for c in m.capabilities}),
                "enabled": any(m.enabled for m in entries),
                "cost_level": active.cost_level if active else None,
                "last_success": st.get(name, {}).get("last_success"),
                "last_error": st.get(name, {}).get("last_error"),
                "latency": st.get(name, {}).get("latency"),
                "status": "not_configured" if not prov.configured() else "configured",
            }
            if test and prov.configured():
                try:  # 유료 생성 API 는 health_check 가 호출하지 않음
                    row["status"] = prov.health_check()
                    self._record(name, True)
                except ProviderError as e:
                    row["status"] = "error"
                    row["last_error"] = scrub(str(e))[:200]
                    self._record(name, False, error=str(e))
            out.append(row)
        return out


__all__ = ["Router", "ProviderError", "ProviderResult", "load_registry", "PROVIDER_CLASSES", "ModelEntry"]
