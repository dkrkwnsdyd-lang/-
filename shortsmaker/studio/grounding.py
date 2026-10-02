"""GROUNDING: AI 가 쓴 대본/문구가 '입력된 사실' 안에 있는지 검증한다.

문제: LLM 은 입력에 없는 문제 상황("밤에 헤맨 적 있죠?"), 장점("설치도 끝나요", "분위기가 싹 달라져요"),
시간대, 비교를 그럴듯하게 지어낸다. 규제 표현(완치/1위) 검사만으로는 이런 '지어낸 장점'을 못 잡는다.

흐름: 생성 -> 판정(별도 LLM 호출) -> 지어낸 주장이 있으면 피드백과 함께 1회 재생성 -> 그래도 있으면 규칙 기반으로 폴백.
판정기가 없거나 실패하면 '검증 불가'로 보고 안전한 규칙 기반으로 간다 (검증 못 한 AI 글은 쓰지 않는다).
"""
from __future__ import annotations

import json
from typing import Callable

from .product import ProductInput

JUDGE_SYSTEM = (
    "You are a strict fact checker for Korean shopping-ad copy. You get ALLOWED FACTS (the only truth) and a list of "
    "copy lines. A line is UNSUPPORTED if it states or implies any fact, benefit, effect, experience, situation, "
    "time of day, problem, comparison, statistic, ease-of-use, quality or atmosphere claim that is NOT contained in "
    "the allowed facts. Also flag lines where the product name or brand is altered, translated or phonetically "
    "rewritten (name_exact must appear as given). "
    "OK: restating an allowed fact in other words; neutral hooks/questions that assert nothing (e.g. '이거 아직 안 써보셨어요?'); "
    "neutral CTAs ('링크에서 확인하세요'); connective phrases; describing what is visible per the allowed facts. "
    'Answer JSON only: {"unsupported":[{"line":"<exact line>","phrase":"<the unsupported part>","reason":"<short>"}]}'
)

RULES_FOR_WRITER = (
    "허용된 사실(allowed_facts)에 있는 내용만 쓴다. 다음은 입력에 없으면 절대 쓰지 않는다: 문제 상황/불편(예: 밤, 어두움, 헤맴), "
    "장점/효과(설치가 쉽다, 분위기가 달라진다, 잘 보인다, 편하다 등), 시간대, 사용 경험, 비교, 후기, 수치. "
    "단, '직접 써본 느낌(사용자 작성)'이 있으면 그 내용에 한해서만 1인칭 경험담(써보니/했더니)으로 말할 수 있다. "
    "문제(problem)가 비어 있으면 문제 제시 장면(problem)을 만들지 말고 story_pattern 은 DISCOVERY 또는 DEMONSTRATION 을 쓴다. "
    "상품명(name_exact)은 한 글자도 바꾸지 말고 그대로 쓴다 (번역/음차 금지). "
    "특징은 '있다/보인다' 수준으로만 말하고 그 특징이 가져오는 이점을 덧붙이지 않는다."
)


def allowed_facts(p: ProductInput, vision: dict | None = None) -> list[str]:
    facts: list[str] = []
    if p.name:
        facts.append(f"상품명: {p.name}")
    facts += [f"특징: {f}" for f in p.features]
    if p.description:
        facts.append(f"설명: {p.description}")
    if p.problem:
        facts.append(f"해결하는 불편(사용자 입력): {p.problem}")
    if p.target:
        facts.append(f"대상: {p.target}")
    if getattr(p, "my_take", ""):
        facts.append(f"직접 써본 느낌(사용자 작성): {p.my_take}")
    if p.price:
        from .coupang import price_is_fresh
        if price_is_fresh(getattr(p, "price_meta", None)):
            suffix = f" (쿠팡 파트너스 API, 조회 {p.price_meta['fetched_at']})" if getattr(p, "price_meta", None) else ""
            facts.append(f"가격: {p.price}{suffix}")
    if vision and not vision.get("error"):
        for ph in vision.get("photos", []):
            facts += [f"사진에 인쇄된 글자: {t}" for t in ph.get("visible_text", [])]
            facts += [f"사진에서 보이는 것: {t}" for t in ph.get("visible_features", [])]
    seen, out = set(), []
    for f in facts:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def judge(router, facts: list[str], lines: list[str], name_exact: str) -> list[dict] | None:
    """지어낸 주장 목록. 판정 자체를 못 하면 None."""
    lines = [l for l in lines if l and l.strip()]
    if not lines:
        return []
    try:
        res = router.run("llm", "json", system=JUDGE_SYSTEM, user=json.dumps(
            {"name_exact": name_exact, "allowed_facts": facts, "lines": lines}, ensure_ascii=False), temperature=0)
    except Exception:
        return None
    if res.provider == "local" or not isinstance(res.value, dict):
        return None
    items = res.value.get("unsupported", [])
    return [i for i in items if isinstance(i, dict) and i.get("phrase")] if isinstance(items, list) else None


def generate_grounded(router, produce: Callable[[str | None], dict], extract_lines: Callable[[dict], list[str]],
                      facts: list[str], name_exact: str, fallback: Callable[[], dict],
                      max_attempts: int = 2) -> tuple[dict, dict]:
    """produce(feedback) -> data. 반환: (data, report)"""
    report: dict = {"attempts": [], "final": "llm"}
    feedback: str | None = None
    for attempt in range(max_attempts):
        try:
            data = produce(feedback)
        except Exception as e:
            report["attempts"].append({"error": str(e)[:160]})
            break
        problems = judge(router, facts, extract_lines(data), name_exact)
        if problems is None:
            report["attempts"].append({"judge": "unavailable"})
            break
        report["attempts"].append({"unsupported": [{"phrase": i["phrase"], "reason": i.get("reason", "")} for i in problems]})
        if not problems:
            return data, report
        feedback = "직전 결과에 입력에 없는 주장이 있었다. 다음 내용을 모두 제거하고 다시 써라: " + \
                   "; ".join(f"'{i['phrase']}' ({i.get('reason', '')})" for i in problems)
    report["final"] = "rule_fallback"
    return fallback(), report
