"""AI 장면 생성 실행: 캐시 확인 → (동의가 있을 때만) provider 호출 → 상품 일치 검사 → 장면에 적용, 실패/불일치는 원본으로 대체.

원칙: 비용은 '동의(consent)'가 있을 때만. 캐시에 있는 결과는 동의 없이도 재사용(무료). provider 실패는 요청당 MAX_PROVIDER_TRIES 개까지만 시도하고, 전체 작업은 절대 실패시키지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import cache as cache_mod
from . import cost as cost_mod
from . import fidelity as fid_mod
from .providers import MAX_PROVIDER_TRIES, GenRequest, ProviderUnavailable, rank

AI_KINDS = ("AI_PRESENTER", "AI_PRODUCT_UGC")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(db, job_id: str, sc, status: str, *, actor_mode: str, cost_mode: str, provider: str | None = None, model: str | None = None,
           cost: float | None = None, key: str | None = None, fidelity: str | None = None, error: str = "", retry: int = 0) -> None:
    if db is None:
        return
    db.execute("INSERT INTO ai_generations (job_id, scene_id, generation_mode, cost_mode, actor_mode, source_type, provider, model, prompt, cache_key,"
               " generation_cost, seconds, generation_status, retry_count, product_fidelity_status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (job_id, sc.scene_id, "hybrid", cost_mode, actor_mode, sc.ai.get("kind"), provider, model, sc.ai.get("prompt"), key, cost,
                sc.ai.get("seconds"), status, retry, fidelity, error[:200], _now()))


def _regen_count(db, key: str) -> int:
    if db is None or not key:
        return 0
    rows = db.query("SELECT COUNT(*) AS n FROM ai_generations WHERE cache_key=? AND generation_status='GENERATED'", (key,))
    return int(rows[0]["n"]) if rows else 0


def _fallback(sc, status: str, reason: str) -> None:
    fb = sc.ai.get("fallback_path") or sc.visual_source.get("fallback_path")
    sc.ai.update({"status": status, "fallback_reason": reason})
    sc.source_type = "PRODUCT_IMAGE"
    sc.visual_source = {"kind": "user_photo", "path": fb, "tier": 1, "reason": f"AI 장면 대체: {reason}"}
    sc.decisions["source"] = f"원본 제품 사진으로 대체 ({reason})"


def _apply(sc, clip: str, secs: float, meta: dict, fidelity: dict) -> None:
    sc.source_type = sc.ai["kind"]
    sc.layout = "lifestyle"
    sc.visual_source = {"kind": "ai_video", "path": clip, "tier": 6, "clip_start": 0.0, "clip_aspect": 0.5625, "window_dur": secs,
                        "reason": "AI 생성 영상" + (" (MOCK)" if meta.get("mock") else ""), "fallback_path": sc.ai.get("fallback_path")}
    sc.duration = round(min(sc.duration, secs), 2) if secs >= 1.2 else sc.duration
    sc.ai.update({"status": meta.get("status_applied", "GENERATED"), "provider": meta.get("provider"), "model": meta.get("model"), "cost": meta.get("cost"),
                  "mock": bool(meta.get("mock")), "fidelity": fidelity.get("status"), "fidelity_detail": fidelity})
    sc.decisions["source"] = f"{sc.ai['kind']} · {meta.get('provider')}" + (" (MOCK)" if meta.get("mock") else "")


def run_generation(scenes: list, *, ctx, db, job_id: str, providers: list, vision_router, cost_mode: str, actor_mode: str, consent: bool,
                   work_dir: Path, cache_dir: Path | None = None) -> dict:
    """반환: {generated, cached, fallbacks, skipped(동의 없음), api_calls, spent(알려진 값), details[]}"""
    out = {"generated": 0, "cached": 0, "fallbacks": 0, "awaiting_consent": 0, "api_calls": 0, "spent": 0.0, "details": []}
    for sc in scenes:
        ai = sc.ai
        if not ai or ai.get("kind") not in AI_KINDS:
            continue
        sid = sc.scene_id
        if ai.get("action") == "revert" or ai.get("status") == "REVERTED":
            _fallback(sc, "REVERTED", "사용자가 원본으로 되돌림")
            out["fallbacks"] += 1
            out["details"].append({"scene_id": sid, "result": "REVERTED"})
            continue
        if ai.get("status") not in ("PLANNED", "FALLBACK_RETRY"):
            continue
        prompt = ai.get("prompt_override") or ai["prompt"]
        ai["prompt"] = prompt
        force = bool(ai.get("force"))
        ref = ai.get("reference_image") or ai.get("fallback_path")
        img_sha = cache_mod.file_sha(ref)
        ranked = rank(providers, ai["kind"], cost_mode)
        pref = ai.get("provider_pref")
        if pref:
            ranked = sorted(ranked, key=lambda p: p.name != pref)
        candidates = ranked[:MAX_PROVIDER_TRIES]
        # 1) 캐시: 동의 없이도 재사용 (비용 없음). provider 후보 + (이전에 생성된) 모든 후보 키를 확인
        hit = None
        if not force:
            for p in (candidates or providers):
                key = cache_mod.key_for(p.name, p.model, ai["kind"], prompt, img_sha, ai["seconds"], ai.get("settings"))
                m = cache_mod.lookup(key, cache_dir)
                if m:
                    hit = (p, key, m)
                    break
        if hit:
            p, key, m = hit
            ai["cache_key"] = key
            fid = m.get("fidelity") or _fidelity(vision_router, ai, m["path"], work_dir)
            if not m.get("fidelity"):
                cache_mod.update_meta(key, {"fidelity": fid}, cache_dir)
            record(db, job_id, sc, "CACHED", actor_mode=actor_mode, cost_mode=cost_mode, provider=m.get("provider"), model=m.get("model"), cost=0.0, key=key,
                   fidelity=fid.get("status"))
            if fid["status"] in ("PASS", "NOT_APPLICABLE"):
                _apply(sc, m["path"], m.get("seconds", ai["seconds"]), {**m, "cost": 0.0, "status_applied": "CACHED"}, fid)
                out["cached"] += 1
                out["details"].append({"scene_id": sid, "result": "CACHED"})
            else:
                _fallback(sc, "PRODUCT_MISMATCH" if fid["status"] == "PRODUCT_MISMATCH" else "FIDELITY_UNVERIFIED",
                          "상품 외형이 원본과 달라 사용하지 않아요 (캐시된 결과)" if fid["status"] == "PRODUCT_MISMATCH" else "원본 상품과 비교할 수 없어 사용하지 않아요")
                sc.ai["fidelity"] = fid["status"]
                sc.ai["fidelity_detail"] = fid
                out["fallbacks"] += 1
                out["details"].append({"scene_id": sid, "result": fid["status"]})
            continue
        # 2) 동의 없이는 호출하지 않는다
        if not consent:
            out["awaiting_consent"] += 1
            ai["status"] = "PLANNED"
            continue
        if not candidates:
            record(db, job_id, sc, "PROVIDER_UNAVAILABLE", actor_mode=actor_mode, cost_mode=cost_mode, error="사용 가능한(검증된+키 있음) provider 없음")
            _fallback(sc, "PROVIDER_UNAVAILABLE", "사용 가능한 영상 생성 provider 가 없어요 (검증/키 필요)")
            out["fallbacks"] += 1
            out["details"].append({"scene_id": sid, "result": "PROVIDER_UNAVAILABLE"})
            continue
        # 3) 재생성 상한
        key0 = cache_mod.key_for(candidates[0].name, candidates[0].model, ai["kind"], prompt, img_sha, ai["seconds"], ai.get("settings"))
        if force and _regen_count(db, key0) > cost_mod.MAX_REGEN.get(cost_mode, 0):
            _fallback(sc, "REGEN_LIMIT", f"재생성 상한({cost_mod.MAX_REGEN.get(cost_mode, 0)}회) 초과")
            out["fallbacks"] += 1
            out["details"].append({"scene_id": sid, "result": "REGEN_LIMIT"})
            continue
        done = False
        for attempt, p in enumerate(candidates):
            key = cache_mod.key_for(p.name, p.model, ai["kind"], prompt, img_sha, ai["seconds"], ai.get("settings"))
            tmp = Path(work_dir) / f"{sid}_{p.name}_{attempt}.mp4"
            try:
                res = p.generate(GenRequest(ai["kind"], prompt, ai["seconds"], ref, settings=ai.get("settings") or {}), tmp)
            except ProviderUnavailable as e:
                record(db, job_id, sc, "PROVIDER_UNAVAILABLE", actor_mode=actor_mode, cost_mode=cost_mode, provider=p.name, model=p.model, key=key, error=str(e), retry=attempt)
                continue
            except Exception as e:                                           # provider 오류 하나가 전체 작업을 깨뜨리지 않는다
                record(db, job_id, sc, "FAILED", actor_mode=actor_mode, cost_mode=cost_mode, provider=p.name, model=p.model, key=key, error=f"{type(e).__name__}: {e}", retry=attempt)
                out["api_calls"] += 1
                continue
            out["api_calls"] += 1
            if res.cost is not None:
                out["spent"] += res.cost
            fid = _fidelity(vision_router, ai, res.path, work_dir)
            meta = {"provider": res.provider, "model": res.model, "kind": ai["kind"], "prompt": prompt, "seconds": res.seconds, "cost": res.cost,
                    "mock": res.mock, "fidelity": fid, "created_at": _now()}
            clip = cache_mod.store(key, res.path, meta, cache_dir)
            ai["cache_key"] = key
            record(db, job_id, sc, "GENERATED", actor_mode=actor_mode, cost_mode=cost_mode, provider=res.provider, model=res.model, cost=res.cost, key=key,
                   fidelity=fid["status"], retry=attempt)
            if fid["status"] in ("PASS", "NOT_APPLICABLE"):
                _apply(sc, clip, res.seconds, {**meta, "status_applied": "GENERATED"}, fid)
                out["generated"] += 1
                out["details"].append({"scene_id": sid, "result": "GENERATED", "provider": res.provider})
            else:
                _fallback(sc, "PRODUCT_MISMATCH" if fid["status"] == "PRODUCT_MISMATCH" else "FIDELITY_UNVERIFIED",
                          "상품 외형이 원본과 달라 이 AI 장면은 사용하지 않아요" if fid["status"] == "PRODUCT_MISMATCH" else "원본 상품과 비교할 수 없어 사용하지 않아요")
                sc.ai.update({"provider": res.provider, "model": res.model, "cost": res.cost, "mock": res.mock, "fidelity": fid["status"], "fidelity_detail": fid})
                out["fallbacks"] += 1
                out["details"].append({"scene_id": sid, "result": fid["status"]})
            done = True
            break                                                            # 상품 불일치도 다른 provider 로 자동 재시도하지 않는다 (비용 폭증 방지)
        if not done:
            _fallback(sc, "FAILED", "AI 영상 생성에 실패했어요 (재시도 상한 도달)")
            out["fallbacks"] += 1
            out["details"].append({"scene_id": sid, "result": "FAILED"})
    out["spent"] = round(out["spent"], 4)
    return out


def _fidelity(router, ai: dict, clip: str, work_dir: Path) -> dict:
    applicable = ai["kind"] == "AI_PRODUCT_UGC"
    return fid_mod.check(router, ai.get("reference_image") or ai.get("fallback_path"), clip, Path(work_dir) / "fidelity", applicable)


def finalize_fallbacks(scenes: list) -> int:
    """최종 렌더 직전: 아직 생성되지 않은(PLANNED) AI 장면은 원본 제품 사진으로 확정한다."""
    n = 0
    for sc in scenes:
        if sc.ai and sc.ai.get("kind") in AI_KINDS and sc.ai.get("status") == "PLANNED":
            _fallback(sc, "NOT_GENERATED", "AI 생성 전(비용 동의 없음)이라 제품 사진 사용")
            n += 1
    return n


def summarize(scenes: list) -> dict:
    ai = [s for s in scenes if s.ai and s.ai.get("kind") in AI_KINDS]
    return {"ai_scene_count": len(ai), "by_status": {st: sum(1 for s in ai if s.ai.get("status") == st) for st in {s.ai.get("status") for s in ai}},
            "ai_seconds_used": round(sum(s.visual_source.get("window_dur", 0) for s in ai if s.visual_source.get("kind") == "ai_video"), 1)}


def estimate_for(scenes: list, providers: list, cost_mode: str, cache_dir: Path | None = None) -> dict:
    """생성 전 비용 표시용: PLANNED AI 장면의 클립 수/길이/요청 수(캐시 제외)/최대 재생성/예상 비용(모르면 '비용 확인 불가')."""
    planned = [s for s in scenes if s.ai and s.ai.get("kind") in AI_KINDS and s.ai.get("status") == "PLANNED"]
    items, cached = [], set()
    for sc in planned:
        ai = sc.ai
        ref = ai.get("reference_image") or ai.get("fallback_path")
        sha = cache_mod.file_sha(ref)
        ranked = rank(providers, ai["kind"], cost_mode)
        key = None
        for p in (ranked or providers):
            k = cache_mod.key_for(p.name, p.model, ai["kind"], ai.get("prompt_override") or ai["prompt"], sha, ai["seconds"], ai.get("settings"))
            if cache_mod.lookup(k, cache_dir) and not ai.get("force"):
                key = k
                cached.add(k)
                break
        items.append({"scene_id": sc.scene_id, "kind": ai["kind"], "seconds": ai["seconds"], "cache_key": key})
    est = cost_mod.estimate(items, lambda kind: (rank(providers, kind, cost_mode) or [None])[0], cached, cost_mode)
    est["providers_available"] = bool([p for p in providers if p.available()])
    if not est["providers_available"] and planned:
        est["note"] = "지금 사용할 수 있는 영상 생성 provider(검증됨+키 있음)가 없어요. 생성을 눌러도 제품 사진으로 대체돼요."
    est["scenes"] = items
    return est
