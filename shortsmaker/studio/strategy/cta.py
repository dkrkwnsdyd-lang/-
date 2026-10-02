"""STEP 6 CTA ENGINE: SCARCITY / LOSS_AVERSION / SOCIAL_PROOF 검토 -> 영상 스타일에 맞는 CTA 하나 + 위치.

SCARCITY 는 입력에 실제 할인/쿠폰/기간/재고가 있을 때만, SOCIAL_PROOF 는 실제 후기/평점이 입력에 있을 때만 쓴다. 없으면 후보에서 제외하고 이유를 기록한다.
"""
from __future__ import annotations

from ..director import clean_sentence, tail_phrase
from .common import (Ctx, SCARCITY, SOCIAL, ask, line_issues, make_caption, num, scale_scores, speak_seconds, strip_marks, tokens, unsupported,
                     verify, weighted)

STRATEGIES = ("SCARCITY", "LOSS_AVERSION", "SOCIAL_PROOF", "DIRECT")
CRITERIA = ("naturalness", "purchase_desire", "target_fit", "selling_point_connection", "action_strength", "ad_resistance", "story_fit")
WEIGHTS = {"naturalness": 0.18, "purchase_desire": 0.16, "target_fit": 0.10, "selling_point_connection": 0.16,
           "action_strength": 0.14, "ad_resistance": 0.14, "story_fit": 0.12}
ACTION = ("링크", "확인", "눌러", "아래", "프로필", "저장")

SYSTEM = (
    "너는 쇼핑 쇼츠 CTA 작가다. '구매 링크는 프로필에 있습니다'로만 끝내지 않는다. 전략: SCARCITY(입력에 실제 할인/쿠폰/기간/재고가 있을 때만), "
    "LOSS_AVERSION(제품을 쓰지 않을 때 계속 겪는 입력된 불편을 상기), SOCIAL_PROOF(입력에 실제 후기/평점이 있을 때만). 조건이 안 되는 전략은 만들지 않는다. "
    "스타일: FAST_COMMERCE=짧고 명확, STORY_AD=이야기의 결말처럼 연결, UGC_REVIEW=개인적인 결론처럼 자연스럽게. 말로 2.8초(약 19자) 이내. 해결을 단정하지 않는다(질문/제안 형태). "
    'JSON: {"ctas":[{"strategy","text","scores":{"naturalness","purchase_desire","target_fit","selling_point_connection","action_strength","ad_resistance","story_fit"}}]}'
)


def eligibility(ctx: Ctx) -> dict:
    ft = ctx.facts_text
    sc = SCARCITY.search(ft)
    so = SOCIAL.search(ft) or ctx.p.review_quotes
    return {"SCARCITY": (bool(sc), "입력에 실제 할인/쿠폰/기간/재고 정보가 있음" if sc else "입력에 확인된 할인·쿠폰·기간·재고가 없어 사용 금지"),
            "LOSS_AVERSION": (bool(ctx.p.problem.strip()), "입력된 불편이 있음" if ctx.p.problem.strip() else "입력된 불편이 없어 상기시킬 것이 없음"),
            "SOCIAL_PROOF": (bool(so), "입력에 실제 후기/평점이 있음" if so else "입력에 확인된 후기·평점이 없어 사용 금지"),
            "DIRECT": (True, "항상 가능 (기본 안내)")}


def rule_ctas(ctx: Ctx, primary: dict | None) -> list[dict]:
    p, short = ctx.p, ctx.short
    prob = clean_sentence(p.problem) if p.problem else ""
    tail = tail_phrase(prob) if prob else ""
    el = eligibility(ctx)
    out = []
    style = ctx.style
    if el["LOSS_AVERSION"][0]:
        text = {"FAST_COMMERCE": "그 불편, 계속 참을 거예요? 링크는 아래에",
                "STORY_AD": "그 불편, 이제 선택할 차례예요. 링크는 아래에",
                "UGC_REVIEW": "그 불편이 신경 쓰이면 링크 걸어둘게요"}[style]
        out.append({"strategy": "LOSS_AVERSION", "text": text})
    if el["SOCIAL_PROOF"][0] and p.review_quotes:
        out.append({"strategy": "SOCIAL_PROOF", "text": "후기 문구는 화면 그대로예요. 링크에서 확인하세요"})
    if el["SCARCITY"][0]:
        m = SCARCITY.search(ctx.facts_text).group(0)
        out.append({"strategy": "SCARCITY", "text": f"{m} 내용은 링크에서 확인하세요"})
    out.append({"strategy": "DIRECT", "text": {"FAST_COMMERCE": "자세한 정보는 링크에서 확인하세요", "STORY_AD": f"{short}, 링크에서 만나보세요",
                                               "UGC_REVIEW": "궁금하면 링크 걸어둘게요"}[style]})
    return out


def _score(ctx: Ctx, primary: dict | None, c: dict, basis: str) -> dict:
    t = strip_marks(c["text"])
    llm = scale_scores(c.get("scores"))
    ref = f"{(primary or {}).get('text', '')} {ctx.p.problem} {' '.join(ctx.p.features)}"
    det = {"action_strength": 55 + 10 * min(3, sum(1 for a in ACTION if a in t)),
           "selling_point_connection": 40 + 30 * min(2, len(tokens(t) & tokens(ref))),
           "ad_resistance": 85 - (25 if SCARCITY.search(t) else 0) - (15 if t.count("!") else 0) - (10 if speak_seconds(t) > 2.6 else 0)}
    base = {"LOSS_AVERSION": (70, 72), "SOCIAL_PROOF": (72, 70), "SCARCITY": (75, 58), "DIRECT": (60, 78)}[c["strategy"]]
    sc = {}
    for k in CRITERIA:
        if k in det:
            sc[k] = round((det[k] + num(llm[k], det[k])) / 2) if k in llm and basis == "llm" else det[k]
        else:
            default = {"purchase_desire": base[0], "naturalness": base[1], "target_fit": 62, "story_fit": 66}[k]
            sc[k] = num(llm.get(k), default)
    return sc


def run(router, ctx: Ctx, primary: dict | None, script: dict, picks: dict | None = None) -> dict:
    el = eligibility(ctx)
    raw = ask(router, SYSTEM, {**ctx.brief(), "eligibility": {k: v[0] for k, v in el.items()}, "primary_selling_point": primary,
                               "script_so_far": [s["narration"] for s in script["scenes"]]}, temperature=0.7)
    cand, basis = [], "rule"
    if raw and isinstance(raw.get("ctas"), list):
        cand = [{"strategy": c.get("strategy"), "text": " ".join(str(c.get("text", "")).split()), "scores": c.get("scores") or {}}
                for c in raw["ctas"] if isinstance(c, dict) and c.get("text")]
        basis = "llm"
        problems = verify(router, ctx, [c["text"] for c in cand])
        if problems is None:
            cand, basis = [], "rule"
        else:
            cand = [c for c in cand if not unsupported(problems, c["text"])]
    ok, rejected = [], []
    for source, b in ((cand, "llm"), (rule_ctas(ctx, primary), "rule")):
        for c in source:
            s = c.get("strategy")
            why = ""
            if s not in STRATEGIES:
                why = "알 수 없는 전략"
            elif not el[s][0]:
                why = el[s][1]
            else:
                bad = [i for i in line_issues(c["text"], ctx) if i["severity"] == "block"]
                if bad:
                    why = "; ".join(i["detail"] for i in bad)
                elif speak_seconds(c["text"]) > 3.4:
                    why = f"말하기에 {speak_seconds(c['text'])}초 - 김"
            if why:
                rejected.append({"strategy": s, "text": c["text"], "why": why})
                continue
            c["scores"] = _score(ctx, primary, c, b)
            c["total"] = weighted(c["scores"], WEIGHTS)
            c["basis"] = b
            c["caption"] = make_caption(c["text"].replace("링크", "[[링크]]", 1)) if "[[" not in c["text"] else make_caption(c["text"])
            ok.append(c)
        if ok and b == "llm" and len(ok) >= 2:
            break
    ok.sort(key=lambda c: -c["total"])
    for i, c in enumerate(ok):
        c["id"] = f"CTA{i + 1}"
    want = ((getattr(ctx, "pattern", None) or {}).get("cta") or {}).get("strategy")        # 참고 패턴의 CTA 방식(soft_recommendation→DIRECT 등)
    if want:
        for c in ok:
            if c["strategy"] == want:
                c["total"] = round(c["total"] + 6, 1)
        ok.sort(key=lambda c: -c["total"])
        for i, c in enumerate(ok):
            c["id"] = f"CTA{i + 1}"
    chosen = next((c for c in ok if c["id"] == (picks or {}).get("cta")), None) or (ok[0] if ok else None)
    n = len(script["scenes"])
    return {"basis": basis, "style": ctx.style, "eligibility": {k: {"allowed": v[0], "why": v[1]} for k, v in el.items()},
            "candidates": ok, "rejected": rejected, "selected": chosen,
            "final": {"position": "마지막 장면 (영상 끝 2~4초)", "scene_index": n - 1, "seconds": [2.0, 4.0]},
            "soft": {"used": False, "reason": "짧은 쇼츠에서는 최종 CTA 하나만 사용 (중간 CTA는 광고 저항을 높임)"}}


def apply(script: dict, cta: dict) -> dict:
    sel = cta.get("selected")
    if not sel:
        return script
    scenes = [dict(s) for s in script["scenes"]]
    last = scenes[-1]
    last.update({"tts_line": sel["text"], "narration": strip_marks(sel["text"]), "caption": sel["caption"], "proof_source": "",
                 "reliability": "B", "cta_strategy": sel["strategy"]})
    from .comment import renumber
    return renumber({**script, "scenes": scenes})
