"""SHOPPING_SHORTS_STRATEGY_ENGINE 공통: 문맥(Ctx), LLM 호출, 사실 안전(FACT SAFETY), 글자/시간 유틸.

원칙
- 모든 단계는 'LLM 제안 + 결정적 코드 검증' 구조. LLM 이 없으면 규칙 기반으로 내려가고 basis="rule" 로 표시한다.
- 입력에 없는 판매량/후기/평점/가격/할인/재고/성능/경험은 만들지 않는다 (등급 A=관측, B=AI 해석, C=확인 불가; C 는 판매 주장/Proof 금지).
- 참고 영상은 '추상 패턴'(reference.FIELDS)만 쓴다. 고유 문장/장면 배열은 받지도 않는다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..director import KOR_CHARS_PER_SEC, clean_sentence, emphasis_of, product_short, strip_marks, tail_phrase
from ..grounding import allowed_facts
from ..product import ProductInput
from ..storyboard.scene_director import DATA_CLAIM, claim_reliability

STYLES = ("FAST_COMMERCE", "STORY_AD", "UGC_REVIEW")
STYLE_KO = {"FAST_COMMERCE": "빠른 상품형", "STORY_AD": "스토리 광고형", "UGC_REVIEW": "사용 후기형"}
STYLE_SECONDS = {"FAST_COMMERCE": (12, 18), "STORY_AD": (15, 25), "UGC_REVIEW": (15, 20)}

CLICHE = re.compile(r"꼭 보세요|꼭 봐|대박|요즘 핫|핫한 (?:제품|템)|아직도? 안 (?:써|사)|안 써보셨|난리|미쳤|역대급|인생템|무조건")
DIRECT_COMMENT = re.compile(r"댓글|여러분.{0,8}(?:생각|의견)|생각은\?|의견.{0,4}(?:주세요|남겨)|남겨\s*주|알려\s*주세요")
SCARCITY = re.compile(r"한정|마감|품절|재고|오늘만|서두르|곧 종료|쿠폰|할인|특가|세일|기간|마지막")
SOCIAL = re.compile(r"후기|리뷰|평점|별점|구매자|만족도|베스트|많이 (?:사|써|팔)|난리|인기|입소문|재구매")
PERFORMANCE = re.compile(r"방수|내구|튼튼|오래 (?:가|간|쓰|돼)|하루 종일|배터리 (?:오래|걱정)|\d+\s*시간|강력|확실히|완벽|최고|최상")
EXPERIENCE = re.compile(
    r"(?:제가|저는|저도|내가|나는|직접|우리 집|저희)[^.?!]{0,12}(?:써|썼|쓰|사용|사봤|샀|구매|먹어|입어|해봤|해보니)"
    r"|써\s?봤|써\s?보니|써\s?본|사용해\s?봤|사용해\s?보니|사\s?봤|샀는데|구매해서|구매했|일주일|한\s?달\s?(?:째|동안)|매일 쓰|재구매|추천드려요|강추")
OVERSEAS_TONE = re.compile(r"!{2,}|놓치지\s*마세요|필수템|신세계|갓성비|미친\s*(?:듯|가성비)|지금\s*당장\s*(?:사|구매)|빨리\s*(?:사|구매)|혁명|인생\s*(?:아이템|템)")
FILLER = re.compile(r"(?<![가-힣])(?:정말|진짜|완전|엄청|너무|굉장히|아주|되게|매우)\s*")
PRAISE = re.compile(r"최고|완벽|끝판왕|역대급|미쳤|대박|인생")


def speak_seconds(text: str) -> float:
    return round(len(re.sub(r"\s+", "", strip_marks(text or ""))) / KOR_CHARS_PER_SEC, 2)


def tokens(text: str) -> set[str]:
    from ..storyboard.scene_director import _tokens
    return _tokens(text or "")


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def category_key(text: str) -> str:
    table = [("camping", ("캠핑", "텐트", "랜턴", "아웃도어", "침낭", "버너")),
             ("fitness", ("운동", "헬스", "마사지", "요가", "러닝", "근육", "스트레칭")),
             ("kitchen", ("주방", "텀블러", "컵", "냄비", "도마", "조리", "보온", "밀폐")),
             ("electronics", ("이어폰", "충전", "블루투스", "케이블", "무선", "LED", "배터리", "전자")),
             ("beauty", ("세럼", "크림", "화장", "스킨", "뷰티")),
             ("living", ("수납", "바스켓", "정리", "청소", "욕실", "거실", "생활"))]
    for key, kws in table:
        if any(k in text for k in kws):
            return key
    return "general"


@dataclass
class Ctx:
    p: ProductInput
    facts: list[str]
    style: str = "FAST_COMMERCE"
    mode: str = "PRO"
    colors: list = field(default_factory=list)
    n_photos: int = 1
    has_clip: bool = False
    reference: dict | None = None            # 추상 패턴만 (reference.FIELDS)
    pattern: dict | None = None              # REFERENCE_VIDEO_ENGINE 가이드 (구조/템포/복제 방지 해시)
    vision: dict | None = None

    @property
    def short(self) -> str:
        return product_short(self.p.name) if self.p.name else "이 제품"

    @property
    def facts_text(self) -> str:
        return " ".join(self.facts)

    @property
    def category(self) -> str:
        return category_key(self.p.text())

    @property
    def seconds(self) -> tuple[int, int]:
        return STYLE_SECONDS.get(self.style, (15, 25))

    def brief(self) -> dict:
        """LLM 에 넘기는 입력 (사진 경로 등 제외). 참고 영상은 추상 패턴만."""
        ref = {}
        if self.reference:
            from ..reference import FIELDS
            ref = {k: self.reference.get(k) for k in FIELDS if self.reference.get(k) not in (None, "", [])}
        return {"name_exact": self.p.name, "allowed_facts": self.facts, "category": self.category,
                "style": self.style, "target_seconds": list(self.seconds), "colors": self.colors, "reference_patterns_abstract": ref,
                "has_real_clip": self.has_clip, "n_photos": self.n_photos}


def make_ctx(p: ProductInput, style: str = "FAST_COMMERCE", mode: str = "PRO", identity=None, vision=None,
             reference: dict | None = None, has_clip: bool = False, pattern: dict | None = None) -> Ctx:
    facts = allowed_facts(p, vision) + [f"후기(사용자 입력): {q}" for q in (p.review_quotes or [])]
    return Ctx(p=p, facts=facts, style=style if style in STYLES else "FAST_COMMERCE", mode=mode,
               colors=list(getattr(identity, "color_reference", []) or []) if identity else [],
               n_photos=len(getattr(identity, "photos", []) or p.photos) if identity else len(p.photos),
               has_clip=has_clip, reference=reference, vision=vision, pattern=pattern)


SAFETY_RULES = (
    "허용된 사실(allowed_facts)에 있는 내용만 주장한다. 판매량/후기수/평점/가격/할인율/재고/마감/순위/성능(방수·사용시간·내구성)/사용 경험은 "
    "allowed_facts 에 있을 때만 쓴다. 없으면 쓰지 않는다. 상품명(name_exact)은 한 글자도 바꾸지 않는다. "
    "'직접 써본 느낌(사용자 작성)'이 있을 때만 1인칭 경험담을 쓴다. 광고 상투구(꼭 보세요/대박/요즘 핫한/아직도 안 써봤어요)와 "
    "댓글 직접 요구(댓글 남겨주세요/여러분 생각은?) 금지. 참고 영상의 문장/장면 배열은 모른다 - 추상 패턴만 참고한다.")


ERRORS: list[str] = []          # 마지막 LLM 실패 사유 (진단용; 엔진이 state 에 기록)


def ask(router, system: str, payload: dict, temperature: float = 0.5, retries: int = 1) -> dict | None:
    """LLM JSON 호출. 실제 LLM 이 없거나 실패하면 None (호출자는 규칙 기반으로 내려간다). 일시 오류는 1회 재시도."""
    if router is None or not router.has_real("llm"):
        return None
    for attempt in range(retries + 1):
        try:
            res = router.run("llm", "json", system=system + "\n" + SAFETY_RULES + "\nJSON 으로만 답한다.",
                             user=json.dumps(payload, ensure_ascii=False), temperature=temperature, max_tokens=7000)
        except Exception as e:
            ERRORS.append(f"{type(e).__name__}: {str(e)[:120]}")
            continue
        if res.provider == "local" or not isinstance(res.value, dict):
            ERRORS.append("LLM 응답이 JSON 객체가 아님")
            continue
        return res.value
    return None


def scale_scores(d) -> dict:
    """LLM 이 1~5 또는 0~1 척도로 줄 때가 있어 0~100 으로 맞춘다."""
    if not isinstance(d, dict):
        return {}
    vals = [float(v) for v in d.values() if isinstance(v, (int, float))]
    if vals and max(vals) <= 1.0:
        return {k: v * 100 for k, v in d.items() if isinstance(v, (int, float))}
    if vals and max(vals) <= 5.0:
        return {k: v * 20 for k, v in d.items() if isinstance(v, (int, float))}
    return {k: v for k, v in d.items() if isinstance(v, (int, float))}


def verify(router, ctx: Ctx, lines: list[str]) -> list[dict] | None:
    """grounding 판정기(별도 LLM 호출)로 입력에 없는 주장을 찾는다. 판정 불가면 None (LLM 글은 쓰지 않는다)."""
    from ..grounding import judge
    texts = [strip_marks(l) for l in lines if l and l.strip()]
    if not texts:
        return []
    for _ in range(2):                                   # 판정기 일시 오류 1회 재시도 (실패하면 LLM 글을 쓰지 않으므로 중요)
        res = judge(router, ctx.facts, texts, ctx.p.name)
        if res is not None:
            return res
    return None


def unsupported(problems: list[dict] | None, text: str) -> dict | None:
    t = strip_marks(text)
    for pr in problems or []:
        ln = strip_marks(str(pr.get("line", "")))
        if ln and (ln == t or ln in t or t in ln or jaccard(ln, t) > 0.8):
            return pr
    return None


def num(v, default=0.0) -> float:
    try:
        return max(0.0, min(100.0, float(v)))
    except (TypeError, ValueError):
        return default


def weighted(scores: dict, weights: dict) -> float:
    tot = sum(weights.values())
    return round(sum(num(scores.get(k), 50) * w for k, w in weights.items()) / tot, 1)


# ------------------------------------------------------------------ FACT SAFETY
def line_issues(text: str, ctx: Ctx, allow_comment_words: bool = False) -> list[dict]:
    """한 줄(대사/자막/후보)의 안전 문제 목록. [{code, detail, severity}] severity: block(쓰면 안 됨) | warn"""
    t = strip_marks(text or "")
    out = []
    if CLICHE.search(t):
        out.append({"code": "cliche", "detail": CLICHE.search(t).group(0), "severity": "block"})
    if not allow_comment_words and DIRECT_COMMENT.search(t):
        out.append({"code": "direct_comment", "detail": DIRECT_COMMENT.search(t).group(0), "severity": "block"})
    if not getattr(ctx.p, "my_take", "") and EXPERIENCE.search(t):       # 사용자가 직접 써본 느낌을 주지 않았다면 사용 경험/구매 후기처럼 말하지 않는다
        out.append({"code": "fake_experience", "detail": EXPERIENCE.search(t).group(0), "severity": "block"})
    if OVERSEAS_TONE.search(t):                                          # 번역투/해외 광고식 과장 (한국 사용자에게 어색한 표현)
        out.append({"code": "overseas_tone", "detail": OVERSEAS_TONE.search(t).group(0), "severity": "block"})
    pat = getattr(ctx, "pattern", None)
    if pat and pat.get("fingerprint"):                                   # 참고 영상의 말/자막과 겹치면 복제 위험
        from ..reference_engine.fingerprint import COPY_THRESHOLD, overlap
        ov = overlap(t, pat["fingerprint"])
        if ov >= COPY_THRESHOLD:
            out.append({"code": "reference_copy", "detail": f"참고 영상 문구와 {int(ov * 100)}% 겹침", "severity": "block"})
    ft = ctx.facts_text
    for rx, code, label in ((SCARCITY, "scarcity_unverified", "확인되지 않은 희소성/할인"),
                            (SOCIAL, "social_unverified", "확인되지 않은 후기/인기")):
        m = rx.search(t)
        if m and m.group(0) not in ft and not (code == "social_unverified" and ctx.p.review_quotes):
            out.append({"code": code, "detail": f"{label}: '{m.group(0)}'", "severity": "block"})
    m = PERFORMANCE.search(t)
    if m and m.group(0) not in ft:
        out.append({"code": "performance_unverified", "detail": f"입력에 없는 성능/과장 표현: '{m.group(0)}'", "severity": "block"})
    rel, claims = claim_reliability(t, ctx.facts)
    for c in claims:
        if c["reliability"] == "C":
            out.append({"code": "data_unverified", "detail": f"입력에 없는 수치/데이터: '{c['text']}'", "severity": "block"})
    return out


def grade(text: str, ctx: Ctx) -> str:
    if any(i["severity"] == "block" and i["code"] in ("data_unverified", "performance_unverified", "scarcity_unverified", "social_unverified")
           for i in line_issues(text, ctx)):
        return "C"
    return claim_reliability(strip_marks(text or ""), ctx.facts)[0]


def make_caption(text: str, emph: str | None = None, max_line: int = 13) -> str:
    """자막: 한 줄 최대 13자, 최대 2줄, 강조 [[ ]] 한 개."""
    t = re.sub(r"\s+", " ", strip_marks(text)).strip()
    words, lines, cur = t.split(" "), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= max_line:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:2]
    cap = "\n".join(lines)
    key = emph if emph and emph in cap else (max((w for w in cap.replace("\n", " ").split(" ")), key=len, default=""))
    return cap.replace(key, f"[[{key}]]", 1) if key else cap
