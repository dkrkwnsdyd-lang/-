"""AI PRESENTER 문구 안전: AI 인물은 '진행자'이지 '가짜 구매자'가 아니다.

사용 경험/구매 후기처럼 들리는 1인칭 표현은 (사용자가 my_take 를 줬더라도) AI 인물의 입으로는 말하지 않는다.
대신 '제품 정보상 확인되는 특징', '이런 상황에서 쓸 수 있는 제품' 같은 설명형 문장을 쓴다.
"""
from __future__ import annotations

import re

from ..director import clean_sentence, product_short
from ..strategy.common import line_issues, strip_marks

from ..strategy.common import EXPERIENCE  # noqa: E402


def experience_issues(text: str) -> list[str]:
    t = strip_marks(text or "")
    return [m.group(0) for m in EXPERIENCE.finditer(t)]


def presenter_problems(text: str, ctx) -> list[dict]:
    """AI 인물이 말하기에 부적합한 이유 목록 (사실 안전 + 가짜 사용 경험)."""
    out = [{"code": "fake_experience", "detail": d, "severity": "block"} for d in experience_issues(text)]
    out += [i for i in line_issues(text, ctx) if i["severity"] == "block"]
    return out


def safe_line(role: str, ctx, features: list[str]) -> tuple[str, str]:
    """(tts, caption). 입력된 특징/불편만 사용하는 설명형 문장."""
    short = ctx.short if ctx else "제품"
    feat = clean_sentence(features[0]) if features else ""
    prob = clean_sentence(ctx.p.problem) if ctx and ctx.p.problem else ""
    if role == "CTA":
        return "제품 정보는 링크에서 확인할 수 있어요", "정보는 [[링크]]에서"
    if feat:
        return f"이 {short}에서 눈에 띄는 부분은 {feat}이에요" if not feat.endswith("요") else f"이 {short}에서 눈에 띄는 부분은 {feat}", f"눈에 띄는 부분\n[[{feat[:11]}]]"
    if prob:
        return f"{prob}, 이런 상황에서 쓸 수 있는 제품이에요", "이런 상황에서\n[[쓰는 제품]]"
    return f"이 {short}, 제품 정보부터 보여드릴게요", f"[[{short}]] 정보"
