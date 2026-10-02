"""COST MODE / 예산 / 생성 전 비용 표시.

- ECONOMY  : AI 영상 생성 없음 (실제 영상/사진/B-roll/FFmpeg/TTS)
- BALANCED : 20초 기준 AI 영상 최대 약 6초 (필요한 장면만)
- PREMIUM  : 20초 기준 AI 영상 최대 약 15초
가격은 provider 가 공식 가격을 알려줄 수 있을 때(price_per_second 가 숫자)만 계산한다. 모르면 None -> '비용 확인 불가'. 임의 숫자를 만들지 않는다.
결제는 하지 않는다: 이 모듈은 '예상'과 '기록'만 한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

COST_MODES = ("ECONOMY", "BALANCED", "PREMIUM")
BASE_SECONDS = {"ECONOMY": 0.0, "BALANCED": 6.0, "PREMIUM": 15.0}      # 20초 영상 기준 AI 영상 최대 길이
MAX_CLIPS = {"ECONOMY": 0, "BALANCED": 2, "PREMIUM": 4}
MAX_REGEN = {"ECONOMY": 0, "BALANCED": 2, "PREMIUM": 2}                # 같은 장면 재생성 상한
CLIP_SECONDS = {"AI_PRESENTER": 4.0, "AI_PRODUCT_UGC": 5.0}
DOWNGRADE = {"PREMIUM": "BALANCED", "BALANCED": "ECONOMY", "ECONOMY": "ECONOMY"}


def ai_seconds_cap(cost_mode: str, total_seconds: float) -> float:
    base = BASE_SECONDS.get(cost_mode, 0.0)
    return round(base * min(1.5, max(0.6, total_seconds / 20.0)), 2)


def month_spend(db, now: datetime | None = None) -> dict:
    """이번 달 기록된 AI 생성 비용 (알려진 값만 합산). {known_total, unknown_count, requests}"""
    now = now or datetime.now(timezone.utc)
    prefix = now.strftime("%Y-%m")
    rows = db.query("SELECT generation_cost, generation_status FROM ai_generations WHERE created_at LIKE ? AND generation_status IN ('GENERATED','FAILED')",
                    (prefix + "%",))
    known = sum(r["generation_cost"] for r in rows if r["generation_cost"] is not None)
    return {"known_total": round(known, 4), "unknown_count": sum(1 for r in rows if r["generation_cost"] is None), "requests": len(rows)}


def apply_budget(cost_mode: str, monthly_budget: float | None, db, projected: float | None = None) -> tuple[str, dict]:
    """월간 예산을 넘으면 PREMIUM→BALANCED→ECONOMY 로 내린다. 사용자 동의 없는 결제는 없다(여기서는 모드만 바꾼다).
    예측 비용을 모르면(None) 예산을 '검증할 수 없음'으로 표시하고, 이미 기록된 지출이 예산 이상일 때만 내린다."""
    info = {"budget": monthly_budget, "spent": None, "downgraded_from": None, "note": ""}
    if not monthly_budget or cost_mode == "ECONOMY":
        return cost_mode, info
    sp = month_spend(db)
    info["spent"] = sp["known_total"]
    mode = cost_mode
    while mode != "ECONOMY" and (sp["known_total"] >= monthly_budget or (projected is not None and sp["known_total"] + projected > monthly_budget)):
        mode = DOWNGRADE[mode]
        projected = None if mode == "ECONOMY" else projected       # 한 단계 내리면 예상은 다시 계산해야 함 (보수적으로 이미 지출만 비교)
    if mode != cost_mode:
        info["downgraded_from"] = cost_mode
        info["note"] = f"월 예산 ${monthly_budget:g} 초과 예상으로 {cost_mode} → {mode}"
    elif projected is None:
        info["note"] = "예상 비용을 알 수 없어 월 예산을 사전 검증할 수 없어요 (기록된 지출만 비교)"
    return mode, info


def estimate(ai_scenes: list[dict], provider_for, cached_keys: set[str] | None = None, cost_mode: str = "BALANCED") -> dict:
    """ai_scenes: [{scene_id, kind, seconds, cache_key?}]. provider_for(kind) -> provider|None.
    반환: 클립 수, 예상 AI 영상 길이, 예상 요청 수(캐시 제외), 최대 재생성, 예상 비용(None=확인 불가)."""
    cached_keys = cached_keys or set()
    by_kind: dict[str, int] = {}
    secs, reqs, cost, unknown = 0.0, 0, 0.0, False
    names = {}
    for s in ai_scenes:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
        secs += s["seconds"]
        if s.get("cache_key") in cached_keys:
            continue
        reqs += 1
        p = provider_for(s["kind"])
        names[s["kind"]] = p.name if p else None
        if p is None or p.price_per_second is None:
            unknown = True
        else:
            cost += p.price_per_second * s["seconds"]
    return {"clips": len(ai_scenes), "by_kind": by_kind, "ai_seconds": round(secs, 1), "requests": reqs, "cached": len(ai_scenes) - reqs,
            "max_regenerations": MAX_REGEN.get(cost_mode, 0),
            "cost_usd": None if unknown else round(cost, 4), "cost_known": not unknown,
            "cost_text": "비용 확인 불가" if unknown else ("$0 (캐시/Mock)" if cost == 0 else f"약 ${cost:.2f}"),
            "providers": names}
