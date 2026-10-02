"""STEP 3 HOOK GENERATOR: PRIMARY_SELLING_POINT + 선택된 Angle 로 첫 3초 Hook 9개(PROBLEM/CURIOSITY/EMPATHY x3) -> BEST_HOOK."""
from __future__ import annotations

import re

from .common import (CLICHE, Ctx, ask, clean_sentence, jaccard, line_issues, make_caption, num, scale_scores, speak_seconds, strip_marks,
                     tail_phrase, tokens, unsupported, verify, weighted)

TYPES = ("PROBLEM", "CURIOSITY", "EMPATHY")
CRITERIA = ("understood_in_3s", "brevity", "target_clear", "pain_link", "next_curiosity", "low_ad_feel")
WEIGHTS = {"understood_in_3s": 0.25, "brevity": 0.15, "target_clear": 0.15, "pain_link": 0.20, "next_curiosity": 0.15, "low_ad_feel": 0.10}
MAX_HOOK_SECONDS = 3.5
STYLE_PREF = {"FAST_COMMERCE": "CURIOSITY", "STORY_AD": "PROBLEM", "UGC_REVIEW": "EMPATHY"}

SYSTEM = (
    "너는 한국 쇼핑 쇼츠 Hook 작가다. 입력의 primary_selling_point 와 selected_angle 에 맞춰 첫 3초 Hook 을 만든다. "
    "먼저 product_shape/color/usage_context/target_customer/pain_point/desire 를 파악(product_analysis 입력 참고)하고 Hook 을 쓴다. "
    "유형별 3개씩 총 9개: PROBLEM(문제 제기형), CURIOSITY(궁금증 유발형), EMPATHY(공감형). "
    "상품과 상관없이 쓸 수 있는 상투적 문구 금지(이거 꼭 보세요 / 대박입니다 / 요즘 핫한 제품 / 아직도 안 써봤어요). "
    "기준: 3초 안에 이해(말로 약 20자 이내), 짧음, 타겟 명확, Pain Point 연결, 다음 장면이 궁금, 광고 느낌 최소. 질문은 제품 사실을 단정하지 않는다. "
    'JSON: {"hooks":[{"type":"PROBLEM|CURIOSITY|EMPATHY","text":"말로 하는 문장","caption":"자막(한 줄 13자 이내, 최대 2줄, 강조는 [[ ]])",'
    '"scores":{"understood_in_3s","brevity","target_clear","pain_link","next_curiosity","low_ad_feel"}}]}'
)


def rule_hooks(ctx: Ctx, primary: dict | None, angle: dict | None) -> list[dict]:
    p, short = ctx.p, ctx.short
    prob = clean_sentence(p.problem) if p.problem else ""
    tail = (prob if len(prob.replace(" ", "")) <= 16 else tail_phrase(prob)) if prob else ""
    feat = (primary or {}).get("feature") or (clean_sentence(p.features[0]) if p.features else "")
    out = []
    if prob:
        out += [("PROBLEM", f"{tail}? 아직도 그냥 참으세요?"), ("PROBLEM", f"{tail}… 이런 순간 있죠?"),
                ("EMPATHY", f"{tail}, 나만 그런 거 아니죠?"), ("EMPATHY", f"{tail}, 이런 적 있죠?")]
        if p.target:
            out.append(("EMPATHY", f"{p.target}이라면 이 장면 공감해요"))
    if feat:
        out += [("CURIOSITY", f"{feat}, 이런 {short} 본 적 있어요?"), ("CURIOSITY", f"이 {short}, 뭐가 다른지 보세요")]
    out.append(("CURIOSITY", f"{short}, 이 부분 보이세요?"))
    if not prob and p.target:
        out.append(("PROBLEM", f"{p.target}이라면 이거 한번 보세요"))
    return [{"type": t, "text": x, "caption": make_caption(x), "scores": {}} for t, x in out]


def _det_scores(ctx: Ctx, text: str, primary: dict | None) -> dict:
    """측정 가능한 항목은 코드로 계산한다 (LLM 이 후하게 줘도 상한이 걸린다)."""
    sec = speak_seconds(text)
    brev = 100 if sec <= 2.2 else 80 if sec <= 3.0 else 55 if sec <= MAX_HOOK_SECONDS else 30
    ref = f"{ctx.p.problem} {(primary or {}).get('text', '')} {' '.join(ctx.p.features)}"
    ov = len(tokens(text) & tokens(ref))
    pain = 40 + 30 * min(2, ov)
    target = 40 + 30 * min(2, len(tokens(text) & tokens(f"{ctx.p.name} {ctx.p.target} {ctx.short}")))
    return {"brevity": brev, "pain_link": pain, "target_clear": target, "_sec": sec}


def _normalize(ctx: Ctx, raw: list[dict], primary: dict | None, basis: str) -> tuple[list[dict], list[dict]]:
    good, rejected = [], []
    for h in raw:
        text = re.sub(r"\s+", " ", strip_marks(str(h.get("text", "")))).strip()
        typ = h.get("type") if h.get("type") in TYPES else "CURIOSITY"
        if not text:
            continue
        issues = [i for i in line_issues(text, ctx) if i["severity"] == "block"]
        if issues:
            rejected.append({"text": text, "type": typ, "why": "; ".join(f"{i['code']}({i['detail']})" for i in issues)})
            continue
        det = _det_scores(ctx, text, primary)
        llm = scale_scores(h.get("scores"))
        sc = {}
        for k in CRITERIA:
            if k in det:
                sc[k] = round((det[k] + num(llm[k], det[k])) / 2) if k in llm and basis == "llm" and k != "brevity" else det[k]
            else:
                sc[k] = num(llm.get(k), 55 if basis == "rule" else 50)
        total = weighted(sc, WEIGHTS)
        cap = make_caption(text) if not h.get("caption") else str(h["caption"])
        if "[[" not in cap:
            cap = make_caption(cap.replace("\n", " "))
        notes = []
        if det["_sec"] > MAX_HOOK_SECONDS:
            notes.append(f"말하기에 {det['_sec']}초 - 3초 안에 이해하기엔 김")
            total = min(total, 60)
        if any(jaccard(text, g["text"]) > 0.7 for g in good):
            continue
        good.append({"text": text, "type": typ, "caption": cap, "scores": sc, "total": total, "seconds": det["_sec"],
                     "notes": notes, "basis": basis})
    good.sort(key=lambda h: -h["total"])
    for i, h in enumerate(good):
        h["id"] = f"H{i + 1}"
    return good, rejected


def run(router, ctx: Ctx, primary: dict | None, angle: dict | None, analysis: dict | None, picks: dict | None = None) -> dict:
    payload = {**ctx.brief(), "primary_selling_point": primary, "selected_angle": angle, "product_analysis": analysis}
    if getattr(ctx, "pattern", None):          # 참고 영상의 Hook 구조(유형/길이)만. 문장은 전달하지 않는다
        payload["reference_hook_structure"] = {"type": ctx.pattern["hook"].get("type"), "pattern": ctx.pattern["hook"].get("pattern"), "max_seconds": ctx.pattern["hook"].get("duration")}
    hooks, rejected, basis = [], [], "rule"
    feedback = ""
    for attempt in range(3):                                   # 검증에서 걸러져 9개가 안 되면 최대 2회 보충 생성 (걸러진 표현을 알려주고)
        need = {t: 3 - sum(1 for h in hooks if h["type"] == t) for t in TYPES}
        if attempt and not any(v > 0 for v in need.values()):
            break
        pl = {**payload, "banned_phrases": [r["why"] for r in rejected if "근거 없는" in r["why"]][:10],
              "need_more": {t: v for t, v in need.items() if v > 0}} if attempt else payload
        raw = ask(router, SYSTEM + (" 이전 결과에서 입력에 근거가 없어 제거된 표현(banned_phrases)은 쓰지 말고, need_more 에 적힌 유형만 부족한 개수만큼 만든다." if attempt else ""), pl, temperature=0.9)
        if not (raw and isinstance(raw.get("hooks"), list)):
            break
        new, rej = _normalize(ctx, raw["hooks"], primary, "llm")
        problems = verify(router, ctx, [h["text"] for h in new])      # 입력에 없는 주장(예: '한 손으로')은 Hook 후보에서 제외
        if problems is None:
            rejected += rej + [{"text": "(LLM Hook 전체)", "type": "-", "why": "사실 검증 불가 - 사용하지 않음"}]
            break
        for h in new:
            pr = unsupported(problems, h["text"])
            if pr:
                rej.append({"text": h["text"], "type": h["type"], "why": f"근거 없는 주장: {pr.get('phrase')}"})
            elif all(jaccard(h["text"], g["text"]) < 0.7 for g in hooks):
                hooks.append(h)
        rejected += rej
        basis = "llm"
    hooks.sort(key=lambda h: -h["total"])
    for i, h in enumerate(hooks):
        h["id"] = f"H{i + 1}"
    if len(hooks) < 3:
        hooks, rej2 = _normalize(ctx, rule_hooks(ctx, primary, angle), primary, "rule")
        rejected += rej2
        basis = "rule"
    pick = (picks or {}).get("hook")
    pat = getattr(ctx, "pattern", None)
    pref = ((pat or {}).get("hook") or {}).get("type") or STYLE_PREF.get(ctx.style)      # 참고 패턴의 Hook 유형이 있으면 그 유형 우선
    for h in hooks:      # 영상 스타일마다 어울리는 Hook 유형이 다르다 (같은 상품 3스타일이 같은 Hook 이 되지 않도록)
        h["style_fit"] = h["total"] + (8 if h["type"] == pref else 0)
    best = next((h for h in hooks if h["id"] == pick), None) or max(hooks, key=lambda h: h["style_fit"], default=None)
    by_type = {t: sum(1 for h in hooks if h["type"] == t) for t in TYPES}
    return {"basis": basis, "candidates": hooks, "selected": best, "rejected": rejected, "by_type": by_type,
            "complete_set": all(v >= 3 for v in by_type.values())}
