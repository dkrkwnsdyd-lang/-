"""SELLING ANGLE → STORY DIRECTOR → HOOK → SCRIPT DIRECTOR → SCENE DIRECTOR V2.

LLM provider 가 있으면 LLM 이 기획하고, 없으면 규칙 기반(rule_director_v1)으로 기획한다.
어느 쪽이든 마지막에 같은 검증/후처리를 거친다 (장면 필드, 길이, 같은 구도 반복 금지).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .. import brain
from .product import ProductIdentity, ProductInput

BEAT_PURPOSE = {
    "hook": "첫 1초 안에 스크롤을 멈추게 한다",
    "problem": "시청자가 공감하는 불편을 보여준다",
    "reveal": "해결책으로 제품을 처음 보여준다",
    "demo": "제품 기능을 눈으로 증명한다",
    "detail": "제품 디테일/특징을 가까이 보여준다",
    "benefit": "사용 후 달라지는 점을 보여준다",
    "cta": "행동을 유도한다",
}
BEAT_DURATION = {  # (min, max) 초
    "hook": (1.6, 2.4), "problem": (1.6, 2.6), "reveal": (1.4, 2.4), "demo": (2.0, 3.4),
    "detail": (1.6, 2.8), "benefit": (1.8, 2.8), "cta": (2.0, 2.8),
}
KOR_CHARS_PER_SEC = 7.0

ANGLE_KEYWORDS = {
    "time_saving": ["빠르", "초 만에", "분 만에", "시간", "단축", "금방", "순식간"],
    "convenience": ["간편", "쉽", "원터치", "버튼 하나", "자동", "세척", "무선", "충전"],
    "portability": ["작", "가벼", "휴대", "미니", "접이", "파우치", "손바닥"],
    "design": ["디자인", "감성", "인테리어", "예쁜", "깔끔"],   # 색상/컬러는 사실이지 장점이 아님
    "pain_relief": ["불편", "뭉", "아프", "피로", "냄새", "얼룩", "먼지", "엉킴", "번거"],
    "gift": ["선물", "기념일", "집들이"],
    "upgrade": ["기존", "대신", "보다", "업그레이드"],
    "value": ["가성비", "리필", "오래", "대용량"],
}
BENEFIT_LINES = {
    "time_saving": ("시간이 확 줄어요", "[[시간]] 확 줄어요"),
    "convenience": ("쓰는 법도 정말 간단해요", "쓰는 법 [[간단]]"),
    "portability": ("가방에 쏙 들어가요", "가방에 [[쏙]]"),
    "design": ("어디에 둬도 깔끔해요", "어디 둬도 [[깔끔]]"),
    "pain_relief": ("이제 그 번거로움이 줄어요", "번거로움 [[끝]]"),
    "gift": ("선물로 주기에도 좋아요", "[[선물]]로도 딱"),
    "upgrade": ("기존 방식이랑은 확실히 달라요", "확실히 [[달라요]]"),
    "value": ("오래 두고 쓰기 좋아요", "[[오래]] 쓰기 좋아요"),
}


@dataclass
class Scene:
    scene_id: str
    beat: str
    duration: float
    purpose: str
    subject: str
    action: str
    environment: str
    product_state: str
    camera_type: str
    camera_angle: str
    camera_motion: str
    shot_size: str
    lighting: str
    emotion: str
    visual_hook: str
    transition: str
    tts_line: str
    caption: str
    reference_image: str | None
    negative_prompt: list[str]
    continuity_rules: list[str]
    shot: str = "hero_push"             # image motion shot type
    emphasis: list[str] = field(default_factory=list)
    start_frame: str = ""               # FIRST / END FRAME DIRECTOR
    end_frame: str = ""
    takes: int = 1
    ref_locked: bool = False            # 사용자가 특징-사진을 연결한 장면: 사진을 바꾸지 않는다
    status: str = "PLANNED"
    story_role: str = ""                # Reference 패턴 스토리 역할(situation/pain/turning/...)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CreativePlan:
    mode: str
    angles: list[dict]
    best_angle: str
    story_pattern: str
    hook_candidates: list[dict]
    hook_type: str
    duration_class: str
    target_duration: tuple[float, float]
    reveal_at: float
    cta_at: float
    scenes: list[Scene]
    director: str
    tension: str = ""
    payoff: str = ""
    compact: bool = False               # 12~15초 압축 구조 (같은 사진의 확대 반복으로 컷 수를 채우지 않는다)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenes"] = [s.to_dict() for s in self.scenes]
        return d

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.scenes), 2)


# ---------------------------------------------------------------- 공통 유틸

def product_short(name: str) -> str:
    """상품명에서 부르기 좋은 짧은 이름 (끝의 수량/용량 표기는 제외: '… 물티슈 100매' -> '물티슈')."""
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    core = [w for w in words if not re.search(r"\d", w)] or words
    return core[-1] if core else "이 제품"


def clean_sentence(text: str) -> str:
    return re.sub(r"[.!?。…~\s]+$", "", text.strip())


def strip_marks(text: str) -> str:
    return text.replace("[[", "").replace("]]", "")


def tail_phrase(text: str, min_chars: int = 6) -> str:
    """문장 끝부분을 자연스럽게 잘라낸다 (예: '텀블러 뚜껑 여는 게 번거로워요' -> '여는 게 번거로워요')."""
    words = clean_sentence(text).split()
    out: list[str] = []
    for w in reversed(words):
        out.insert(0, w)
        if len("".join(out)) >= min_chars and len(out[0]) > 1:
            break
    return " ".join(out)


def _linked_photo(beat: dict, feature_photos: dict[str, str]) -> str | None:
    """장면이 어떤 특징을 보여주는지 찾아 그 특징에 연결된 사진을 돌려준다.
    LLM 이 feature 를 빼거나 살짝 바꿔도, 자막/대사에 특징의 단어가 겹치면 연결한다 (유일하게 가장 많이 겹칠 때만)."""
    if not feature_photos or beat.get("beat") not in ("demo", "detail"):
        return None
    exact = feature_photos.get(beat.get("feature") or "")
    if exact:
        return exact
    text = strip_marks(f"{beat.get('caption', '')} {beat.get('tts_line', '')}")
    scores = {}
    for feat in feature_photos:
        toks = [t for t in re.split(r"\s+", feat) if len(t) >= 2]
        scores[feat] = sum(1 for t in toks if t in text)
    best = max(scores.values(), default=0)
    winners = [f for f, sc in scores.items() if sc == best]
    return feature_photos[winners[0]] if best >= 1 and len(winners) == 1 else None


def emphasis_of(caption: str) -> list[str]:
    return re.findall(r"\[\[(.+?)\]\]", caption)


def josa(word: str, pair: tuple[str, str]) -> str:
    """받침 유무로 조사 선택. pair=(받침O, 받침X) 예: ("이", "가")"""
    if not word:
        return pair[1]
    ch = word[-1]
    if "가" <= ch <= "힣":
        return pair[0] if (ord(ch) - 0xAC00) % 28 else pair[1]
    return pair[1]


COMPACT_DURATION = {"hook": 1.2, "reveal": 2.7, "demo": 3.6, "detail": 3.0, "benefit": 3.3, "cta": 3.0}
COMPACT_RANGE = (12.0, 15.0)


def compact_beats(beats: list[dict]) -> list[dict]:
    """12~15초 구조: 강한 훅(0~1.2) -> 제품 공개 -> 사용/기능 시연 -> 핵심 혜택/결과 -> 짧은 CTA.
    문제(problem) 장면은 훅으로 흡수하고, 각 역할마다 1개만 남겨 같은 내용의 반복으로 시간을 채우지 않는다."""
    def first(*names):
        return next((b for b in beats if b["beat"] in names), None)
    hook, reveal, cta = first("hook"), first("reveal"), beats[-1]
    demo = first("demo")
    rest = [b for b in beats if b not in (hook, reveal, demo, cta) and b["beat"] in ("detail", "benefit", "demo")]
    demo = demo or (rest.pop(0) if rest else None)
    benefit = next((b for b in rest if b["beat"] == "benefit"), None) or (rest[0] if rest else None)
    out = [b for b in (hook, reveal, demo, benefit) if b]
    if len(out) < 3 and (problem := first("problem")):          # 재료가 부족하면 문제 장면으로 보충 (입력에 문제가 있을 때만 존재)
        out.insert(1, problem)
    return out + [cta]


def decide_duration_class(pattern: str, n_features: int, mode: str) -> tuple[str, tuple[float, float]]:
    rules = brain.system("core_rules")["duration_rules"]
    if mode == "FAST":
        return "fast", tuple(brain.system("core_rules")["modes"]["FAST"]["duration"])
    if pattern in ("FAIL_SUCCESS", "COMPARISON", "MYTH_REALITY") and n_features >= 2:
        return "story", tuple(rules["story"])
    if n_features <= 1:
        return "simple", tuple(rules["simple"])
    return "standard", tuple(rules["standard"])


# ---------------------------------------------------------------- SELLING ANGLE

def selling_angles(p: ProductInput) -> list[dict]:
    weights = brain.system("selling_angle_rules")["scoring"]
    text = p.text()
    out = []
    for angle, kws in ANGLE_KEYWORDS.items():
        evidence = [f for f in p.features + [p.description, p.problem] if f and any(k in f for k in kws)]
        if not evidence and not any(k in text for k in kws):
            continue
        ev = min(1.0, len(evidence) / 2)
        visual = 0.9 if angle in ("convenience", "portability", "design", "time_saving") else 0.6
        emotional = 0.9 if angle in ("pain_relief", "time_saving", "gift") else 0.6
        score = round(100 * (weights["evidence"] * ev + weights["visual_demonstrability"] * visual
                             + weights["emotional_pull"] * emotional))
        out.append({"angle": angle, "score": score, "evidence": evidence[:3],
                    "reason": brain.system("selling_angle_rules")["angles"][angle]})
    if p.problem and not any(a["angle"] == "pain_relief" for a in out):
        out.append({"angle": "pain_relief", "score": 70, "evidence": [p.problem],
                    "reason": brain.system("selling_angle_rules")["angles"]["pain_relief"]})
    if not out:
        out.append({"angle": "convenience", "score": 50, "evidence": [], "reason": "근거 부족 - 기본 각도"})
    return sorted(out, key=lambda a: a["score"], reverse=True)


# ---------------------------------------------------------------- STORY / HOOK (rule director)

def choose_story(p: ProductInput, mode: str) -> str:
    text = p.text()
    if any(k in text for k in (" vs ", "기존 제품", "대신 쓰", "비교")):
        return "COMPARISON"
    if p.problem:
        return "PROBLEM_SOLUTION"
    if mode == "FAST":
        return "DEMONSTRATION"
    return "DISCOVERY"


TESTABLE_KEYWORDS = ["강도", "충전", "배터리", "세척", "흡입", "보온", "보냉", "방수", "소음", "속도", "모드", "진동", "무선"]


def hook_candidates(p: ProductInput, story: str) -> list[dict]:
    short = product_short(p.name)
    feat = clean_sentence(p.features[0]) if p.features else ""
    out = []
    if p.problem:
        prob = clean_sentence(p.problem)
        tail = tail_phrase(prob)
        out += [
            {"type": "existing_behavior_negation", "text": f"{prob}? 아직도 그냥 참으세요?",
             "caption": f"{tail}?\n아직도 [[참으세요]]?"},
            {"type": "question_reveal", "text": f"{prob}? 이거 보면 생각 바뀌어요",
             "caption": f"{tail}?\n이거 보면 [[생각 바뀜]]"},
            {"type": "discovery", "text": f"{prob}, 저만 그런 거 아니죠?",
             "caption": f"{tail}\n[[나만]] 그래?"},
        ]
    # '진짜 되는지'는 기능/성능을 시험할 수 있는 제품에만 (컵·바구니 같은 제품엔 어색함)
    testable = any(k in p.text() for k in TESTABLE_KEYWORDS)
    if testable:
        out.append({"type": "test_challenge", "text": f"이 {short}, 진짜 되는지 보세요",
                    "caption": f"이 {short}\n[[진짜]] 될까?"})
    else:
        out.append({"type": "discovery", "text": f"이 {short}, 아직 안 써보셨어요?",
                    "caption": f"이 {short}\n아직 [[안 써봤다면]]?"})
    out += [
        {"type": "pov", "text": f"{feat} {short}, 직접 보여드릴게요" if feat else f"{short}, 직접 보여드릴게요",
         "caption": f"[[{feat or short}]]\n직접 보세요"},
    ]
    if story == "COMPARISON":
        out.insert(0, {"type": "comparison", "text": f"기존 거랑 이 {short}, 차이 보이세요?",
                       "caption": f"기존 vs [[{short}]]\n차이 보여요?"})
    return out[:3]


def josa_end(word: str, end: str) -> str:
    """'이 있어요'/'도 있어요' 같은 어미가 받침 유무에 맞게 이어지도록 (링 + 이 있어요 -> '링이 있어요', 기능 + 이 있어요 -> '기능이 있어요', 거치대 + 가...)."""
    ch = word[-1] if word else ""
    has_final = bool(ch) and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0
    if end.startswith("이 "):
        return (end if has_final else "가 " + end[2:])
    return end


def feature_lines(features: list[str]) -> list[tuple[str, str]]:
    suffixes = ["", "게다가 ", "그리고 "]
    ends = ["이 있어요", "까지 돼요", "도 있어요"]      # 사실만: 특징이 '있다'고만 말한다 (크기/장점 주장 금지)
    out = []
    for i, f in enumerate(features[:4]):
        f = clean_sentence(f)
        tts = f"{suffixes[min(i, 2)]}{f}{josa_end(f, ends[i % 3])}"
        # 숫자/첫 단어를 강조
        m = re.search(r"\d[\d.,]*\s*\S*", f)
        key = m.group(0) if m else f.split(" ")[0]
        cap = f.replace(key, f"[[{key}]]", 1)
        out.append((tts, cap))
    return out


def mystery_director(p: ProductInput, mode: str) -> dict:
    """사진만 있고 상품 정보가 없을 때: 효능/정보를 지어내지 않고 '궁금증 → 공개' 구조로 시각 중심 연출."""
    beats = [
        {"beat": "hook", "tts_line": "이게 뭔지 맞혀보세요", "caption": "이게 [[뭘까요]]?", "shot": "macro"},
        {"beat": "detail", "tts_line": "힌트, 이 디테일", "caption": "힌트는 [[이 디테일]]", "shot": "detail_pan"},
        {"beat": "reveal", "tts_line": "정답은 바로 이거예요", "caption": "정답은 [[바로 이거]]", "shot": "whip_reveal"},
        {"beat": "demo", "tts_line": "가까이 보면 이런 느낌", "caption": "가까이 보면 [[이런 느낌]]", "shot": "macro"},
    ]
    if mode != "FAST":
        beats.append({"beat": "benefit", "tts_line": "전체 모습은 이렇게", "caption": "전체 [[모습]]", "shot": "parallax"})
    beats.append({"beat": "cta", "tts_line": "자세한 정보는 링크에서 확인하세요", "caption": "정보는 [[링크]]에서"})
    return {"angles": [{"angle": "design", "score": 40, "evidence": [], "reason": "상품 정보 없음 - 외형 중심"}],
            "best_angle": "design", "story_pattern": "QUESTION_REVEAL",
            "hook_candidates": [{"type": "question_reveal", "text": beats[0]["tts_line"], "caption": beats[0]["caption"]}],
            "beats": beats, "tension": "무슨 제품인지에 대한 궁금증", "payoff": "제품 전체 공개"}


def rule_director(p: ProductInput, mode: str) -> dict:
    if not p.name.strip() or p.name == "이 제품":
        if not p.features and not p.problem:
            return mystery_director(p, mode)
    angles = selling_angles(p)
    story = choose_story(p, mode)
    hooks = hook_candidates(p, story)
    short = product_short(p.name)
    feats = feature_lines(p.features) or [(f"{short}, 한 번 보세요", f"[[{short}]]")]
    best = angles[0]["angle"]
    beats: list[dict] = [{"beat": "hook", "tts_line": hooks[0]["text"], "caption": hooks[0]["caption"]}]
    if p.problem and story in ("PROBLEM_SOLUTION", "COMPARISON", "BEFORE_AFTER"):
        prob = clean_sentence(p.problem)
        tail = tail_phrase(prob)
        beats.append({"beat": "problem", "tts_line": f"매번 {prob}… 은근 스트레스죠",
                      "caption": f"매번 [[{tail}]]\n은근 스트레스"})
    if p.problem:
        beats.append({"beat": "reveal", "tts_line": "그럴 땐 이거 하나면 돼요", "caption": f"그럴 땐 [[{short}]]"})
    else:   # 문제 제시가 없는데 '그럴 땐'은 성립하지 않음
        beats.append({"beat": "reveal", "tts_line": f"바로 이 {short}예요", "caption": f"바로 이 [[{short}]]"})
    n_feat = 1 if mode == "FAST" else 3
    for i, (tts, cap) in enumerate(feats[:n_feat]):
        beats.append({"beat": "demo" if i == 0 else "detail", "tts_line": tts, "caption": cap,
                      "feature": p.features[i] if i < len(p.features) else None})
    if mode != "FAST" or len(beats) < 4:
        if angles[0]["evidence"]:
            tts, cap = BENEFIT_LINES.get(best, BENEFIT_LINES["convenience"])
        else:   # 근거 있는 장점이 없으면 효과를 주장하지 않고 실제 모습만 보여준다
            tts, cap = "실제로 놓으면 이런 모습이에요", "실제 [[모습]]은 이렇게"
        beats.append({"beat": "benefit", "tts_line": tts, "caption": cap})
    beats.append({"beat": "cta", "tts_line": "자세한 정보는 링크에서 확인하세요", "caption": "정보는 [[링크]]에서"})
    return {"angles": angles, "best_angle": best, "story_pattern": story, "hook_candidates": hooks,
            "beats": beats, "tension": p.problem or "제품이 정말 되는지에 대한 궁금증",
            "payoff": BENEFIT_LINES.get(best, BENEFIT_LINES["convenience"])[0] if angles[0]["evidence"]
            else "제품의 실제 모습을 보여준다"}


# ---------------------------------------------------------------- LLM director

def llm_director(router, p: ProductInput, identity: ProductIdentity, mode: str, vision: dict | None = None) -> dict:
    """SYSTEM RULES 와 JOB DATA 를 분리해서 LLM 에 넘긴다. 결과는 grounding 검증을 통과해야 쓴다."""
    from . import grounding
    core = brain.system("core_rules")
    facts = grounding.allowed_facts(p, vision)
    base_system = "\n".join([
        "너는 한국 쇼핑 쇼츠 디렉터다. 광고 설명문 말투 금지, 친구에게 추천하듯 짧은 구어체.",
        "원칙: " + " / ".join(core["principles"]),
        "스토리 패턴: " + ", ".join(brain.system("story_patterns")["patterns"]),
        "후킹 공식(문장 복사 금지, 공식만 참고): " + json.dumps(
            {k: v["formula"] for k, v in brain.system("hook_patterns")["patterns"].items()}, ensure_ascii=False),
        "자막 규칙: 한 줄 최대 13자, 최대 2줄, 강조 단어는 [[ ]] 로 감싼다.",
        "TTS 규칙: " + json.dumps(brain.system("tts_rules"), ensure_ascii=False),
        "beat 는 hook, problem, reveal, demo, detail, benefit, cta 중에서. 제품을 0초에 무조건 노출하지 않는다.",
        "입력에 없는 판매량, 후기수, 순위, 효능, 인증, 특허, 수치는 절대 만들지 않는다.",
        grounding.RULES_FOR_WRITER,
        'JSON 으로만 답한다: {"angles":[{"angle","score","evidence","reason"}],"best_angle","story_pattern",'
        '"hook_candidates":[{"type","text","caption"}],"beats":[{"beat","tts_line","caption","feature"}],"tension","payoff"} '
        "(demo/detail 의 feature 에는 그 장면이 보여주는 특징 문장을 입력 그대로 넣는다)",
    ])
    job = {"mode": mode, "name_exact": p.name, "allowed_facts": facts,
           "product": {k: v for k, v in asdict(p).items() if k not in ("photos", "product_boxes", "feature_photos", "claim_sources")},
           "identity": {"colors": identity.color_reference, "missing_angles": identity.missing_angles}}
    meta: dict = {}

    def produce(feedback: str | None) -> dict:
        system = base_system + ("\n" + feedback if feedback else "")
        res = router.run("llm", "json", system=system, user="JOB DATA:\n" + json.dumps(job, ensure_ascii=False),
                         temperature=0.4)
        if res.provider == "local":
            raise RuntimeError("LLM 사용 불가")
        d = res.value
        d["_director"] = f"{res.provider}:{res.model}"
        return d

    def lines(d: dict) -> list[str]:
        out = [h.get("text", "") for h in d.get("hook_candidates", [])[:1]]
        for b in d.get("beats", []):
            out += [b.get("tts_line", ""), strip_marks(b.get("caption", "")).replace("\n", " ")]
        return out

    data, report = grounding.generate_grounded(router, produce, lines, facts, p.name, lambda: rule_director(p, mode))
    if report["final"] == "rule_fallback":
        data["_director"] = "local:rule_director_v1 (LLM 글이 근거 검증 실패)"
    data["_grounding"] = report
    return _enforce_problem_rule(data, p)


PROBLEM_STORIES = ("PROBLEM_SOLUTION", "COMPARISON", "BEFORE_AFTER", "FAIL_SUCCESS")


def _enforce_problem_rule(data: dict, p: ProductInput) -> dict:
    """결정적 안전장치: 사용자가 문제를 입력하지 않았으면 문제 제시 장면/스토리를 쓰지 않는다."""
    if p.problem.strip():
        return data
    data["beats"] = [b for b in data.get("beats", []) if b.get("beat") != "problem"]
    if data.get("story_pattern") in PROBLEM_STORIES:
        data["story_pattern"] = "DISCOVERY"
    return data


# ---------------------------------------------------------------- SCENE DIRECTOR V2

ZOOM_SHOTS = ("macro", "detail_pan")
MIN_ZOOM_SIDE = 900
SAFE_ALT = ["hero_push", "parallax", "light_sweep", "rack_focus"]


def zoomable(identity: ProductIdentity, path: str | None) -> bool:
    """확대 컷은 제품 위치를 알 수 있을 때만: 단색 배경 사진(제품 영역 추정 가능)이거나 focus 지정.
    복잡한 배경 사진은 확대하면 배경(나무/사물)을 잡아서 제품이 아닌 곳을 보여준다."""
    for ph in identity.photos:
        if ph["path"] == path:
            if min(ph["width"], ph["height"]) < MIN_ZOOM_SIDE:   # 저해상도 원본은 확대하면 뭉개진다
                return False
            if ph.get("quality_grade") == "C":                    # 품질 부족 사진은 확대하지 않는다
                return False
            return ph["background"] == "plain" or bool(ph.get("focus"))
    return False


def safe_shot(beat: str, prev: str | None, index: int) -> str:
    pool = [x for x in SAFE_ALT if x != prev]
    if beat == "hook":
        return "punch_in" if prev != "punch_in" else pool[0]
    if beat == "reveal":
        return "whip_reveal" if prev != "whip_reveal" else pool[0]
    if beat == "cta":
        return "cta_card"
    return pool[index % len(pool)]


def _pick_shot(beat: str, prev: str | None, index: int) -> str:
    options = brain.system("scene_rules")["beat_to_shot"][beat]
    for i in range(len(options)):
        shot = options[(index + i) % len(options)]
        if shot != prev:
            return shot
    return options[0]


def _ref_for(beat: str, shot: str, identity: ProductIdentity, index: int, pool: list[str] | None = None) -> str | None:
    photos = [ph["path"] for ph in identity.photos]
    if pool and beat in ("hook", "reveal", "demo", "detail", "benefit"):     # 일상 속 상품: 일상(배경이 있는) 사진을 돌려 쓴다
        return pool[index % len(pool)]
    if shot in ("macro", "detail_pan"):
        return identity.detail_reference or identity.front_reference
    if beat in ("benefit",) and identity.usage_reference:
        return identity.usage_reference
    if beat in ("reveal", "cta", "hook"):
        return identity.front_reference
    return photos[index % len(photos)] if photos else None


def direct_scenes(plan_data: dict, identity: ProductIdentity, p: ProductInput, mode: str) -> CreativePlan:
    rules = brain.system("scene_rules")
    cams = brain.system("camera_patterns")["shots"]
    story = plan_data.get("story_pattern") or "DISCOVERY"
    if story not in brain.system("story_patterns")["patterns"]:
        story = "DISCOVERY"
    beats = [b for b in plan_data.get("beats", []) if b.get("beat") in BEAT_PURPOSE]
    if not beats or beats[-1]["beat"] != "cta":
        beats.append({"beat": "cta", "tts_line": "자세한 정보는 링크에서 확인하세요", "caption": "정보는 [[링크]]에서"})
    dclass, (dmin, dmax) = decide_duration_class(story, len(p.features), mode)
    compact = bool(getattr(p, "compact", False))
    if compact:
        beats = compact_beats(beats)
        dclass, (dmin, dmax) = "compact", COMPACT_RANGE
    max_scenes = 5 if (mode == "FAST" or compact) else 8
    if len(beats) > max_scenes:
        beats = beats[:max_scenes - 1] + [beats[-1]]

    daily_pool = None
    if getattr(p, "content_type", "PRODUCT") == "DAILY":        # 일상(배경 있는) 사진을 먼저, 부족하면 나머지 사진을 섞어 같은 사진이 반복되지 않게
        life = [ph["path"] for ph in identity.photos if ph.get("background") == "busy"]
        daily_pool = (life + [ph["path"] for ph in identity.photos if ph["path"] not in life]) if life else None
    scenes: list[Scene] = []
    feature_photos = getattr(p, "feature_photos", {}) or {}   # pipeline 이 저장된 사진 경로로 변환해 둔 값
    prev_shot = None
    for i, b in enumerate(beats):
        beat = b["beat"]
        tts = strip_marks(b.get("tts_line", "")).strip()
        caption = b.get("caption") or tts
        lo, hi = BEAT_DURATION[beat]
        dur = min(hi, max(lo, len(tts.replace(" ", "")) / KOR_CHARS_PER_SEC + 0.35))
        hinted = b.get("shot")
        shot = hinted if hinted in brain.system("camera_patterns")["shots"] and hinted != prev_shot \
            else _pick_shot(beat, prev_shot, i)
        ref = _ref_for(beat, shot, identity, i, daily_pool)
        locked = False
        linked = _linked_photo(b, feature_photos)
        if linked:
            ref, locked = linked, True
        if shot in ZOOM_SHOTS and not zoomable(identity, ref):
            shot = safe_shot(beat, prev_shot, i)
        prev_shot = shot
        cam = cams[shot]
        takes_rule = brain.system("core_rules")["modes"][mode]["takes"]
        takes = takes_rule if isinstance(takes_rule, int) else takes_rule.get(beat, takes_rule["other"])
        scenes.append(Scene(
            scene_id=f"S{i + 1}", beat=beat, duration=round(dur, 2), purpose=BEAT_PURPOSE[beat],
            subject=identity.name if beat != "problem" else (p.target or "일상 속 사용자"),
            action={"hook": "시선을 끄는 움직임으로 시작", "problem": "불편한 상황 강조",
                    "reveal": "제품 첫 등장", "demo": "기능이 보이도록 가까이",
                    "detail": "특징 부분 클로즈업", "benefit": "완성된 모습", "cta": "제품 정면 마무리"}[beat],
            environment="clean studio backdrop" if beat != "benefit" else "lifestyle",
            product_state="hidden" if beat == "problem" else "visible, identical to reference",
            camera_type=cam["camera_type"], camera_angle="eye level" if beat != "detail" else "slightly top-down",
            camera_motion=cam["motion"], shot_size=cam["shot_size"],
            lighting="soft natural daylight" if beat != "problem" else "cool, low saturation",
            emotion={"hook": "curious", "problem": "frustrated", "reveal": "relief", "demo": "impressed",
                     "detail": "interested", "benefit": "satisfied", "cta": "confident"}[beat],
            visual_hook="punch zoom on first beat" if beat == "hook" else "",
            transition="cut" if i == 0 else ("whip" if beat in ("reveal",) else "cut"),
            tts_line=tts, caption=caption, reference_image=ref,
            negative_prompt=list(rules["default_negative"]),
            continuity_rules=["same product_id " + identity.product_id, "same color", "same logo",
                              "same button position", "same proportions"],
            shot=shot, emphasis=emphasis_of(caption), takes=takes, ref_locked=locked,
            story_role=b.get("story_role", ""),
            start_frame=f"{identity.name} {'held in frame' if beat != 'problem' else 'not visible'}",
            end_frame={"reveal": "product fully visible, centered", "demo": "feature clearly visible",
                       "cta": "product hero, centered"}.get(beat, "same framing, product unchanged"),
        ))

    # 첫 3초 규칙: 공개 전 장면(hook, problem)은 짧게 -> 제품 공개 2~4초
    seen_reveal = False
    for s in scenes:
        if s.beat == "reveal":
            seen_reveal = True
        elif not seen_reveal:
            s.duration = 1.8 if s.beat == "hook" else 1.5
    if compact:
        for s in scenes:
            s.duration = COMPACT_DURATION.get(s.beat, 2.5)
    # 목표 길이 범위로 보정 (공개 이후 장면만 스케일, 비트별 한계 유지)
    total = sum(s.duration for s in scenes)
    target = min(max(total, dmin), dmax)
    reveal_idx = next((i for i, s in enumerate(scenes) if s.beat == "reveal"), 0)
    post = scenes[reveal_idx:]
    fixed = total - sum(s.duration for s in post)
    if abs(total - target) > 0.05 and post and not compact:
        k = (target - fixed) / (total - fixed)
        for s in post:
            lo, hi = BEAT_DURATION[s.beat]
            s.duration = round(min(hi * 1.25, max(lo * 0.8, s.duration * k)), 2)

    # 제품 공개 시점 / CTA 시점
    t, reveal_at, cta_at = 0.0, 0.0, 0.0
    for s in scenes:
        if s.beat == "reveal" and not reveal_at:
            reveal_at = t
        if s.beat == "cta":
            cta_at = t
        t += s.duration

    hooks = plan_data.get("hook_candidates") or []
    return CreativePlan(
        mode=mode, angles=plan_data.get("angles", []), best_angle=plan_data.get("best_angle", ""),
        story_pattern=story, hook_candidates=hooks, hook_type=hooks[0]["type"] if hooks else "unknown",
        duration_class=dclass, target_duration=(dmin, dmax), reveal_at=round(reveal_at, 2),
        cta_at=round(cta_at, 2), scenes=scenes, director=plan_data.get("_director", "local:rule_director_v1"),
        tension=plan_data.get("tension", ""), payoff=plan_data.get("payoff", ""), compact=compact)
