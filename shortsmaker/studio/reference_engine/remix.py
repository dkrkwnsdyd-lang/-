"""LICENSED_REMIX_MODE: 사용자가 직접 만들었거나 사용 권한을 확보한 영상만 실제 클립을 재편집(Crop/Trim/Reorder/Caption/TTS/Transition/Motion/BGM)할 수 있다.

외부 URL 의 영상, 권한이 확인되지 않은 업로드는 대상이 아니다. 이번 범위는 '권한 표시/검문'과 기존 REAL_UGC 배치 재사용까지(구조 단계).
권한은 사용자의 자기 선언이다(OWNED=내가 만든 영상, LICENSED=사용 허락을 받은 영상). 시스템이 진위를 확인할 수는 없다.
"""
from __future__ import annotations

from dataclasses import dataclass

ALLOWED_RIGHTS = ("OWNED", "LICENSED")
OPERATIONS = ("crop", "trim", "reorder", "caption", "tts", "transition", "motion", "bgm")


class RemixNotAllowed(Exception):
    pass


@dataclass
class RemixSource:
    path: str
    rights: str = "NONE"
    attested_by_user: bool = False
    origin: str = "upload"          # upload | url


def can_remix(src: RemixSource) -> tuple[bool, str]:
    if src.origin != "upload":
        return False, "외부 URL 영상은 Licensed Remix 대상이 아니에요 (분석용 Reference 로만 사용 가능)"
    if src.rights not in ALLOWED_RIGHTS:
        return False, "사용 권한이 확인되지 않은 영상이에요 (직접 만든 영상이거나 사용 허락을 받은 영상만 재편집할 수 있어요)"
    if not src.attested_by_user:
        return False, "권한 확인(체크)이 필요해요"
    return True, ""


def ensure_licensed(sources: list[RemixSource]) -> list[RemixSource]:
    bad = [(s, can_remix(s)[1]) for s in sources if not can_remix(s)[0]]
    if bad:
        raise RemixNotAllowed("; ".join(f"{s.path}: {why}" for s, why in bad))
    return sources


def plan(sources: list[RemixSource], ops: list[str] | None = None) -> dict:
    """허용 연산 검증 + 사용할 소스 목록. 실제 편집은 기존 파이프라인(REAL_UGC 배치/자막/TTS/전환/모션/BGM)이 한다."""
    ops = [o for o in (ops or list(OPERATIONS)) if o in OPERATIONS]
    ensure_licensed(sources)
    return {"mode": "LICENSED_REMIX", "sources": [s.path for s in sources], "operations": ops, "actor_mode": "REAL_UGC"}
