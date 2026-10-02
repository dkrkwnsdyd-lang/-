"""STORYBOARD JSON 스키마. AI(기획) 와 Renderer(영상 생성)를 분리하는 계약.

AI 쪽은 Storyboard 만 만들고, Renderer 는 Storyboard 만 읽어서 MP4 를 만든다.
나중에 AI 모델을 바꿔도 이 스키마만 지키면 Renderer 는 그대로 쓸 수 있다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1

SCENE_TYPES = ("HOOK", "PROBLEM", "PRODUCT_REVEAL", "FEATURE", "DEMO", "BENEFIT", "PROOF", "CTA")
# 기존(legacy) 비트 이름과의 대응: 기존 director/editor/QA 는 비트 이름을 쓴다.
BEAT_TO_TYPE = {"hook": "HOOK", "problem": "PROBLEM", "reveal": "PRODUCT_REVEAL", "detail": "FEATURE",
                "demo": "DEMO", "benefit": "BENEFIT", "cta": "CTA"}
TYPE_TO_BEAT = {**{v: k for k, v in BEAT_TO_TYPE.items()}, "PROOF": "benefit"}

# 영상 길이별 권장 장면 수 (지시서): 12초 4~6 / 20초 6~9 / 30초 8~12 / 45초 10~15
DURATION_CLASSES = (("12s", 16.0, (4, 6)), ("20s", 25.0, (6, 9)), ("30s", 37.5, (8, 12)), ("45s", 9999.0, (10, 15)))

# 정보 신뢰 등급: A = 실제 관측 데이터(사용자 입력/사진에 인쇄된 글자), B = AI 해석, C = 확인 불가
RELIABILITY = ("A", "B", "C")


def duration_class(total_seconds: float) -> tuple[str, tuple[int, int]]:
    for name, upper, rng in DURATION_CLASSES:
        if total_seconds <= upper:
            return name, rng
    return DURATION_CLASSES[-1][0], DURATION_CLASSES[-1][2]


@dataclass
class StoryScene:
    scene_id: str
    scene_type: str
    duration: float
    purpose: str
    narration: str
    main_caption: str
    sub_caption: str = ""
    visual_source: dict = field(default_factory=dict)      # {kind, path, box, tier, reason, gap?}
    visual_prompt: str = ""                                 # 생성이 필요한 장면에만 (사진/영상으로 해결되면 빈 값)
    layout: str = ""                                        # Layout Engine
    camera_motion: str = ""                                 # 카메라 움직임 설명
    image_motion: str = ""                                  # Motion Director 의 motion id
    text_animation: str = "word_pop"
    transition: str = "cut"                                 # cut | whip | flash | soft
    sound_effect: list = field(default_factory=list)       # [{"sfx","at"("start"|"emphasis"|"end"),"gain"}]
    music_cue: str = ""
    emphasis: list = field(default_factory=list)
    # --- 부가 정보 (렌더러/Preview 용)
    legacy_beat: str = ""
    secondary_source: str = ""                              # split/comparison 등 두 번째 이미지
    layout_data: dict = field(default_factory=dict)         # 레이아웃이 쓰는 실제 데이터 {items, callout, quote, rows ...} (신뢰 등급 A 만)
    reliability: str = "A"                                  # 이 장면 문구의 신뢰 등급 중 가장 낮은 값
    claims: list = field(default_factory=list)              # [{"text","reliability","note"}]
    decisions: dict = field(default_factory=dict)           # {"layout": 이유, "motion": 이유, ...} 감사용
    scene_role: str = ""                                    # Strategy Engine: HOOK|PROBLEM|SOLUTION|PROOF|CTA
    source_type: str = ""                                   # PRODUCT_IMAGE|PRODUCT_VIDEO|REAL_UGC|AI_PRESENTER|AI_PRODUCT_UGC|BROLL|TEXT_ONLY (빈 값=PRODUCT_IMAGE)
    ai: dict = field(default_factory=dict)                  # AI 장면 정보 {kind, status, provider, model, prompt, seconds, cost, retry_count, fidelity, cache_key, mock, fallback_path}
    product_visibility: str = ""                            # NONE|HINT|PARTIAL|FULL

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Storyboard:
    scenes: list[StoryScene]
    mode: str = "PRO"
    style: str = "STANDARD"
    total_duration: float = 0.0
    duration_class: str = ""
    scene_range: tuple[int, int] = (0, 0)
    music: dict = field(default_factory=dict)
    facts: list = field(default_factory=list)              # [{"text","reliability"}]
    warnings: list = field(default_factory=list)
    issues: list = field(default_factory=list)             # 품질 규칙 위반 (validate)
    production: dict = field(default_factory=dict)         # 출연 방식/비용 모드/AI 장면 계획과 예상 비용 (presenter.plan)
    version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scene_range"] = list(self.scene_range)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Storyboard":
        d = dict(d)
        scenes = [StoryScene(**{k: v for k, v in s.items() if k in StoryScene.__dataclass_fields__}) for s in d.pop("scenes", [])]
        d["scene_range"] = tuple(d.get("scene_range", (0, 0)))
        return cls(scenes=scenes, **{k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "scenes"})

    @classmethod
    def from_json(cls, text: str) -> "Storyboard":
        return cls.from_dict(json.loads(text))

    def scene(self, scene_id: str) -> StoryScene | None:
        return next((s for s in self.scenes if s.scene_id == scene_id), None)
