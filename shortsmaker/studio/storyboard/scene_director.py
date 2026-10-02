"""SCENE DIRECTOR - 장면마다 '무엇을 말하고, 무엇을 보여주고, 어떻게 보여줄지'를 결정한다.

대본(Script)만 만드는 것이 아니라 각 장면의 narration/자막/소스/연출 필드를 모두 채운다.
Layout 과 Motion 은 각각 layouts.py / motion_director.py 가 정하고, 이 모듈이 호출한다.
데이터 신뢰도(A 관측 / B AI 해석 / C 확인 불가)를 장면마다 기록해서, 입력에 없는 가격·후기·성능이 자막에 섞이면 표시한다.
"""
from __future__ import annotations

import re

from .. import director as legacy
from . import sources
from .schema import BEAT_TO_TYPE, StoryScene

TEXT_ANIMATION = {"HOOK": "word_pop", "PROBLEM": "word_pop", "PRODUCT_REVEAL": "scale_pop", "FEATURE": "word_pop",
                  "DEMO": "word_pop", "BENEFIT": "fade_in", "PROOF": "fade_in", "CTA": "slide_up"}
MUSIC_CUE = {"HOOK": "intro: 첫 박에 바로 시작 (정적 금지)", "PROBLEM": "tension: 저음 유지, 볼륨 살짝 낮춤",
             "PRODUCT_REVEAL": "drop: 라이저 뒤 임팩트로 제품 공개", "FEATURE": "groove: 리듬 유지",
             "DEMO": "steady: 시연에 집중, 음량 낮게", "BENEFIT": "lift: 밝게 상승", "PROOF": "steady",
             "CTA": "resolve: 마무리, 점점 줄어듦"}
# 입력에 없으면 지어내면 안 되는 데이터성 표현 (판매량/후기/평점/가격/할인/성능 수치/인증)
DATA_CLAIM = re.compile(r"\d[\d,.]*\s*(?:%|원|만원|개|명|배|시간|분|초|W|mAh|인치|kg|g|cm|mm|단계)|평점|별점|후기|리뷰|할인|판매량|1위|베스트|특가|품절|인증|특허|무료배송|최저가")
RANK = {"A": 0, "B": 1, "C": 2}


def split_caption(caption: str) -> tuple[str, str, list[str]]:
    """자막 -> (main, sub, emphasis). 읽는 순서를 유지한다: main = 첫 줄, sub = 나머지 줄. 강조 단어는 emphasis 목록으로."""
    emph = legacy.emphasis_of(caption)
    lines = [ln.strip() for ln in legacy.strip_marks(caption).split("\n") if ln.strip()]
    if not lines:
        return "", "", emph
    return lines[0], "\n".join(lines[1:]), emph


def caption_text(scene) -> str:
    """Storyboard 의 main/sub 자막 -> 렌더러가 쓰는 자막 문자열 ([[강조]] 표시 복원). Preview 에서 사용자가 고친 자막도 같은 경로."""
    out, used = [], set()
    for ln in [scene.main_caption] + ([scene.sub_caption] if scene.sub_caption else []):
        for w in sorted({e for e in scene.emphasis if e}, key=len, reverse=True):
            if w not in used and w in ln and "[[" not in ln:
                ln = ln.replace(w, f"[[{w}]]", 1)
                used.add(w)                                        # 강조 단어는 한 번만 표시
        out.extend(ln.split("\n"))
    return "\n".join(out)


# 사실 여부와 무관한 문법/연결 표현 (판정 대상에서 제외)
NEUTRAL = {"있어요", "돼요", "이에요", "예요", "에요", "해요", "입니다", "그리고", "게다가", "바로", "이", "그", "저", "것"}
_PARTICLES = ("까지", "으로", "에서", "이", "가", "은", "는", "을", "를", "도", "에", "의", "로", "와", "과")


def _stem(tok: str) -> str:
    for ps in _PARTICLES:
        if tok.endswith(ps) and len(tok) > len(ps):
            return tok[: -len(ps)]
    return tok


def _tokens(text: str) -> set[str]:
    """내용어 토큰 (조사 제거, 문법/연결 표현 제외)."""
    raw = re.findall(r"[0-9A-Za-z가-힣+\-]+", text.lower())
    return {_stem(t) for t in raw if t not in NEUTRAL and _stem(t) not in NEUTRAL}


def claim_reliability(text: str, facts: list[str]) -> tuple[str, list[dict]]:
    """(장면 등급, 데이터성 주장 목록). 데이터성 표현이 입력 사실에 없으면 C, 사실과 겹치면 A, 일반 표현은 B."""
    fact_text = " ".join(facts)
    claims, worst = [], "A"
    for m in DATA_CLAIM.finditer(text):
        supported = m.group(0).strip() in fact_text or re.sub(r"\s+", "", m.group(0)) in re.sub(r"\s+", "", fact_text)
        claims.append({"text": m.group(0), "reliability": "A" if supported else "C",
                       "note": "입력 사실에 있음" if supported else "입력에 없는 데이터성 표현 - 확인 불가"})
        if not supported and RANK["C"] > RANK[worst]:
            worst = "C"
    if worst != "C":
        toks = _tokens(text)
        covered = len(toks & _tokens(fact_text)) / len(toks) if toks else 0.0
        worst = "A" if covered >= 0.6 else "B"   # 문장 대부분이 입력 사실이면 관측(A), 아니면 AI 해석/일반 표현(B)
    return worst, claims


def transition_for(scene_type: str, index: int) -> str:
    if index == 0:
        return "cut"
    return {"PRODUCT_REVEAL": "whip", "CTA": "flash"}.get(scene_type, "cut")      # CTA 전에는 별도 시각 변화


class SceneDirector:
    def __init__(self, identity, product, facts: list[str], clip_paths: list[str] | None = None):
        self.identity, self.p, self.facts = identity, product, facts
        self.clips = list(clip_paths or [])
        self.cams = legacy.brain.system("camera_patterns")["shots"]
        self.ai_used = 0

    def from_legacy(self, sc, index: int) -> StoryScene:
        stype = "PROOF" if getattr(sc, "beat", "") == "proof" else BEAT_TO_TYPE[sc.beat]
        main, sub, emph = split_caption(sc.caption)
        narration = legacy.strip_marks(sc.tts_line)
        rel, claims = claim_reliability(f"{main} {sub} {narration}", self.facts)
        src = sources.route_visual_source(stype, sc.reference_image, self.identity, self.clips, self.identity.name,
                                          list(self.p.features), self.ai_used)
        if src.get("ai_candidate"):
            self.ai_used += 1
        box = next((ph.get("product_box") for ph in self.identity.photos if ph["path"] == src.get("path")), None)
        if box:
            src["box"] = list(box)
        cam = self.cams.get(sc.shot, {})
        return StoryScene(
            scene_id=sc.scene_id, scene_type=stype, duration=round(sc.duration, 2), purpose=sc.purpose,
            narration=narration, main_caption=main, sub_caption=sub, visual_source=src,
            visual_prompt=src.pop("visual_prompt", ""), camera_motion=cam.get("motion", ""),
            text_animation=TEXT_ANIMATION.get(stype, "word_pop"), transition=transition_for(stype, index),
            music_cue=MUSIC_CUE.get(stype, ""), emphasis=emph, legacy_beat=sc.beat, story_role=getattr(sc, "story_role", ""),
            reliability=rel, claims=claims,
            decisions={"source": src.get("reason", ""), "transition": f"{stype} → {transition_for(stype, index)}",
                       "legacy_shot": sc.shot})
