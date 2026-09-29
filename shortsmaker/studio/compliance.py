"""PLATFORM COMPLIANCE GATE: PRODUCT / CONTENT / CLAIM / DISCLOSURE (+ RIGHTS).

키워드만으로 차단하지 않고 카테고리·문맥·근거 여부를 함께 본다.
UNKNOWN 은 절대 자동으로 GREEN 처리하지 않는다.
"""
from __future__ import annotations

import re

from .. import brain
from .product import ProductInput

PLATFORMS = ("youtube", "instagram", "tiktok", "threads")
CATEGORY_HINTS = {  # UI 카테고리 -> 정책 카테고리
    "생활": "general_goods", "유아": "general_goods", "육아": "general_goods", "주방": "general_goods", "전자기기": "general_goods", "패션": "general_goods",
    "반려동물": "general_goods", "문구": "general_goods", "인테리어": "general_goods",
    "뷰티": "cosmetics", "화장품": "cosmetics", "운동": "general_goods", "건강": "health_supplement",
    "식품": "health_supplement", "의료기기": "medical_device", "주류": "alcohol",
}
NEGATION = re.compile(r"(아닙니다|아니에요|아님|않습니다|않아요|없습니다|금지|주의)")


def product_risk(p: ProductInput) -> dict:
    cats = brain.policy("common")["categories"]
    text = p.text()
    hits = []
    for name, c in cats.items():
        for kw in c["keywords"]:
            if kw and kw.lower() in text.lower():
                hits.append((name, c["risk"], kw))
    hint_cat = CATEGORY_HINTS.get(p.category_hint.strip())
    order = {"RED": 3, "YELLOW": 2, "GREEN": 1}
    if hits:
        name, risk, kw = max(hits, key=lambda h: order[h[1]])
        return {"risk": risk, "category": name, "evidence": [f"'{h[2]}' -> {h[0]}" for h in hits]}
    if hint_cat:
        return {"risk": cats[hint_cat]["risk"], "category": hint_cat, "evidence": [f"카테고리 입력: {p.category_hint}"]}
    return {"risk": "UNKNOWN", "category": "unknown", "evidence": ["카테고리 미입력, 키워드 없음 - 사람 확인 필요"]}


def claim_check(texts: dict[str, str], p: ProductInput, category: str) -> list[dict]:
    """texts: {위치: 문장}. 근거/출처에 따라 상태를 매긴다."""
    rules = brain.policy("korea")["claim_rules"]
    user_text = " ".join([p.name, p.description, " ".join(p.features)])
    found = []
    for where, text in texts.items():
        for sentence in re.split(r"(?<=[.!?\n])\s*", text):
            for rname, rule in rules.items():
                for pat in rule["patterns"]:
                    m = re.search(pat, sentence)
                    if not m:
                        continue
                    phrase = m.group(0)
                    if NEGATION.search(sentence[m.end():m.end() + 12]):
                        continue   # "치료 목적이 아닙니다" 같은 부정 문맥
                    if any(phrase in k or k in phrase for k in p.claim_sources):
                        status = "SOURCE_BACKED"
                    elif phrase in user_text:
                        status = "USER_PROVIDED" if rule["status"] != "HIGH_RISK" else "HIGH_RISK"
                    else:
                        status = rule["status"]
                    found.append({"where": where, "phrase": phrase, "rule": rname, "status": status,
                                  "sentence": sentence.strip()[:120]})
    return found


def health_check(texts: dict[str, str], category: str) -> list[str]:
    topics = brain.policy("korea")["health_rules"]["sensitive_topics"]
    joined = " ".join(texts.values())
    hits = [t for t in topics if t in joined]
    if hits and category in ("health_supplement", "medical_device", "cosmetics"):
        return [f"민감 주제 '{h}' - 효능 표현 재확인 필요" for h in hits]
    return []


def disclosure_check(affiliate: str, copies: dict[str, dict], in_video_label: bool) -> dict:
    required = brain.policy("korea")["disclosure_rules"].get(affiliate)
    if affiliate == "NONE" or not required:
        return {"required": False, "status": "PASS", "missing": []}
    missing = []
    for platform, c in copies.items():
        body = " ".join(str(v) for v in c.values())
        if required[:12] not in body:
            missing.append(platform)
    if not in_video_label:
        missing.append("in_video_label")
    return {"required": True, "text": required, "status": "PASS" if not missing else "REQUIRES_EDIT",
            "missing": missing}


def rights_check(assets: list[dict]) -> dict:
    r = brain.system("rights_rules")
    blocked = [a for a in assets if a["rights"] in r["never_in_render"]]
    warn = [a for a in assets if a["rights"] in r["warn_in_render"]]
    status = "BLOCKED" if blocked else ("PASS_WITH_WARNING" if warn else "PASS")
    return {"status": status, "blocked": [a["path"] for a in blocked], "unknown": [a["path"] for a in warn]}


def platform_verdicts(risk: dict, claims: list[dict], health: list[str], disclosure: dict, rights: dict) -> dict:
    out = {}
    for pf in PLATFORMS:
        pol = brain.policy(pf)
        reasons = []
        verdict = "PASS"
        if rights["status"] == "BLOCKED":
            verdict, reasons = "BLOCKED", ["REFERENCE_ONLY 자산이 영상에 포함됨"]
        elif risk["risk"] == "RED" or risk["category"] in pol["prohibited_categories"]:
            verdict, reasons = "BLOCKED", [f"금지 카테고리: {risk['category']}"]
        elif risk["risk"] == "UNKNOWN":
            verdict, reasons = "UNKNOWN", ["상품 카테고리 확인 필요"]
        else:
            if any(c["status"] == "HIGH_RISK" for c in claims):
                verdict = "REQUIRES_EDIT"
                reasons.append("고위험 표현: " + ", ".join(sorted({c["phrase"] for c in claims if c["status"] == "HIGH_RISK"})))
            if disclosure["status"] != "PASS":
                verdict = "REQUIRES_EDIT"
                reasons.append("광고/제휴 고지 누락: " + ", ".join(disclosure["missing"]))
            if verdict == "PASS":
                if risk["category"] in pol["restricted_categories"] or risk["risk"] == "YELLOW":
                    verdict = "PASS_WITH_WARNING"
                    reasons.append(f"제한 카테고리({risk['category']}) - 플랫폼 규정 확인")
                if any(c["status"] == "UNVERIFIED" for c in claims):
                    verdict = "PASS_WITH_WARNING"
                    reasons.append("근거 없는 표현: " + ", ".join(sorted({c["phrase"] for c in claims if c["status"] == "UNVERIFIED"})))
                if health:
                    verdict = "PASS_WITH_WARNING"
                    reasons += health
                if rights["status"] == "PASS_WITH_WARNING":
                    verdict = "PASS_WITH_WARNING"
                    reasons.append("권리 불명 자산 포함")
        out[pf] = {"verdict": verdict, "reasons": reasons, "disclosure_hint": pol["disclosure_rules"]}
    return out


def compliance_gate(p: ProductInput, texts: dict[str, str], copies: dict[str, dict],
                    in_video_label: bool, assets: list[dict]) -> dict:
    risk = product_risk(p)
    all_texts = dict(texts)
    for pf, c in copies.items():
        for k, v in c.items():
            if isinstance(v, str):
                all_texts[f"{pf}.{k}"] = v
    claims = claim_check(all_texts, p, risk["category"])
    health = health_check(all_texts, risk["category"])
    disclosure = disclosure_check(p.affiliate, copies, in_video_label)
    rights = rights_check(assets)
    verdicts = platform_verdicts(risk, claims, health, disclosure, rights)
    return {"product": risk, "claims": claims, "health": health, "disclosure": disclosure,
            "rights": rights, "platforms": verdicts,
            "claims_status": "HIGH_RISK" if any(c["status"] == "HIGH_RISK" for c in claims)
            else "UNVERIFIED" if any(c["status"] == "UNVERIFIED" for c in claims) else "PASS"}
