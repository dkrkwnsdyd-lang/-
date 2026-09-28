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
    "design": ["디자인", "감성", "인테리어", "색상", "컬러", "예쁜", "깔끔"],
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
    status: str = "PLANNED"

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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenes"] = [s.to_dict() for s in self.scenes]
        return d

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.scenes), 2)


# ---------------------------------------------------------------- 공통 유틸

def product_short(name: str) -> str:
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    return words[-1] if words else "이 제품"


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
    out += [
        {"type": "test_challenge", "text": f"이 {short}, 진짜 되는지 보세요",
         "caption": f"이 {short}\n[[진짜]] 될까?"},
        {"type": "pov", "text": f"{feat} {short}, 직접 보여드릴게요" if feat else f"{short}, 직접 보여드릴게요",
         "caption": f"[[{feat or short}]]\n직접 보세요"},
    ]
    if story == "COMPARISON":
        out.insert(0, {"type": "comparison", "text": f"기존 거랑 이 {short}, 차이 보이세요?",
                       "caption": f"기존 vs [[{short}]]\n차이 보여요?"})
    return out[:3]


def feature_lines(features: list[str]) -> list[tuple[str, str]]:
    suffixes = ["", "게다가 ", "그리고 "]
    ends = [", 이게 생각보다 커요", "까지 돼요", ", 이것도 좋아요"]
    out = []
    for i, f in enumerate(features[:4]):
        f = clean_sentence(f)
        tts = f"{suffixes[min(i, 2)]}{f}{ends[i % 3]}"
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
    beats.append({"beat": "reveal", "tts_line": "그럴 땐 이거 하나면 돼요",
                  "caption": f"그럴 땐 [[{short}]]"})
    n_feat = 1 if mode == "FAST" else 3
    for i, (tts, cap) in enumerate(feats[:n_feat]):
        beats.append({"beat": "demo" if i == 0 else "detail", "tts_line": tts, "caption": cap})
    if mode != "FAST" or len(beats) < 4:
        tts, cap = BENEFIT_LINES.get(best, BENEFIT_LINES["convenience"])
        beats.append({"beat": "benefit", "tts_line": tts, "caption": cap})
    beats.append({"beat": "cta", "tts_line": "자세한 정보는 링크에서 확인하세요", "caption": "정보는 [[링크]]에서"})
    return {"angles": angles, "best_angle": best, "story_pattern": story, "hook_candidates": hooks,
            "beats": beats, "tension": p.problem or "제품이 정말 되는지에 대한 궁금증",
            "payoff": BENEFIT_LINES.get(best, BENEFIT_LINES["convenience"])[0]}


# ---------------------------------------------------------------- LLM director

def llm_director(router, p: ProductInput, identity: ProductIdentity, mode: str) -> dict:
    """SYSTEM RULES 와 JOB DATA 를 분리해서 LLM 에 넘긴다."""
    core = brain.system("core_rules")
    system = "\n".join([
        "너는 한국 쇼핑 쇼츠 디렉터다. 광고 설명문 말투 금지, 친구에게 추천하듯 짧은 구어체.",
        "원칙: " + " / ".join(core["principles"]),
        "스토리 패턴: " + ", ".join(brain.system("story_patterns")["patterns"]),
        "후킹 공식(문장 복사 금지, 공식만 참고): " + json.dumps(
            {k: v["formula"] for k, v in brain.system("hook_patterns")["patterns"].items()}, ensure_ascii=False),
        "자막 규칙: 한 줄 최대 13자, 최대 2줄, 강조 단어는 [[ ]] 로 감싼다.",
        "TTS 규칙: " + json.dumps(brain.system("tts_rules"), ensure_ascii=False),
        "beat 는 hook, problem, reveal, demo, detail, benefit, cta 중에서. 제품을 0초에 무조건 노출하지 않는다.",
        "입력에 없는 판매량, 후기수, 순위, 효능, 인증, 특허, 수치는 절대 만들지 않는다.",
        'JSON 으로만 답한다: {"angles":[{"angle","score","evidence","reason"}],"best_angle","story_pattern",'
        '"hook_candidates":[{"type","text","caption"}],"beats":[{"beat","tts_line","caption"}],"tension","payoff"}',
    ])
    job = {"mode": mode, "product": asdict(p), "identity": {
        "colors": identity.color_reference, "features": identity.distinctive_features,
        "missing_angles": identity.missing_angles}}
    job["product"].pop("photos", None)
    res = router.run("llm", "json", system=system, user="JOB DATA:\n" + json.dumps(job, ensure_ascii=False),
                     local_fn=lambda: rule_director(p, mode))
    data = res.value
    data["_director"] = f"{res.provider}:{res.model}"
    return data


# ---------------------------------------------------------------- SCENE DIRECTOR V2

def _pick_shot(beat: str, prev: str | None, index: int) -> str:
    options = brain.system("scene_rules")["beat_to_shot"][beat]
    for i in range(len(options)):
        shot = options[(index + i) % len(options)]
        if shot != prev:
            return shot
    return options[0]


def _ref_for(beat: str, shot: str, identity: ProductIdentity, index: int) -> str | None:
    photos = [ph["path"] for ph in identity.photos]
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
    max_scenes = 5 if mode == "FAST" else 8
    if len(beats) > max_scenes:
        beats = beats[:max_scenes - 1] + [beats[-1]]

    scenes: list[Scene] = []
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
        prev_shot = shot
        cam = cams[shot]
        ref = _ref_for(beat, shot, identity, i)
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
            shot=shot, emphasis=emphasis_of(caption), takes=takes,
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
    # 목표 길이 범위로 보정 (공개 이후 장면만 스케일, 비트별 한계 유지)
    total = sum(s.duration for s in scenes)
    target = min(max(total, dmin), dmax)
    reveal_idx = next((i for i, s in enumerate(scenes) if s.beat == "reveal"), 0)
    post = scenes[reveal_idx:]
    fixed = total - sum(s.duration for s in post)
    if abs(total - target) > 0.05 and post:
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
        tension=plan_data.get("tension", ""), payoff=plan_data.get("payoff", ""))
