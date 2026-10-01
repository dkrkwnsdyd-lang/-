"""SCENE LAYOUT ENGINE - 장면마다 화면 구성(레이아웃)을 고른다. 슬라이드쇼/PPT 처럼 보이지 않게.

규칙
- 연속 장면에 같은 레이아웃 금지, 전체에서도 반복을 벌점으로 억제
- 같은 '계열'(전면/카드/분할/텍스트)이 연달아 나오는 것도 벌점 (CTA 직전은 CTA(카드) 와 다른 계열)
- 상품 중심점이 항상 화면 중앙이 되지 않도록 비중앙 레이아웃을 일정 비율 이상 사용 (4장면 이상)
- 사용할 수 없는 레이아웃은 후보에서 제외: 후기/비교/전후는 사용자가 준 실제 데이터가 있을 때만(지어내지 않음),
  데모/라이프스타일은 사용 장면(영상/사용 사진)이 있을 때만
- 랜덤 없음: 같은 입력이면 같은 결과 (선택 이유를 decisions 에 기록)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

LAYOUTS = ["full_product", "product_center", "split_screen", "before_after", "problem_solution", "feature_callout", "review_quote",
           "three_benefits", "comparison", "close_up", "lifestyle", "product_overlay", "floating_product", "text_focus", "demo",
           "result", "cta"]

FAMILY = {"full_product": "fill", "close_up": "fill", "lifestyle": "fill", "demo": "fill",
          "product_center": "card", "floating_product": "card", "result": "card", "cta": "card",
          "split_screen": "split", "before_after": "split", "problem_solution": "split", "comparison": "split",
          "text_focus": "text", "review_quote": "text", "three_benefits": "text", "feature_callout": "text", "product_overlay": "text"}
OFF_CENTER = {"feature_callout", "product_overlay", "split_screen", "three_benefits", "problem_solution", "before_after", "comparison",
              "review_quote", "text_focus"}

# 장면 유형별 적합도 (0~10)
FITNESS = {
    "HOOK": {"full_product": 9, "close_up": 8, "text_focus": 6, "floating_product": 6, "product_overlay": 5, "product_center": 4, "feature_callout": 3},
    "PROBLEM": {"problem_solution": 9, "text_focus": 7, "before_after": 7, "lifestyle": 6, "close_up": 4, "product_overlay": 4},
    "PRODUCT_REVEAL": {"product_center": 8, "floating_product": 8, "full_product": 7, "product_overlay": 6, "result": 5},
    "FEATURE": {"feature_callout": 9, "close_up": 8, "split_screen": 7, "three_benefits": 7, "product_overlay": 5, "full_product": 4},
    "DEMO": {"demo": 9, "lifestyle": 8, "split_screen": 6, "close_up": 6, "feature_callout": 5, "full_product": 4},
    "BENEFIT": {"result": 9, "three_benefits": 8, "lifestyle": 7, "before_after": 7, "product_overlay": 6, "floating_product": 5},
    "PROOF": {"review_quote": 9, "comparison": 8, "three_benefits": 6, "text_focus": 5},
    "CTA": {"cta": 10, "product_center": 3},
}
LABELS = {"full_product": "상품 전면", "product_center": "상품 중앙", "split_screen": "화면 분할", "before_after": "전/후 비교",
          "problem_solution": "문제→해결", "feature_callout": "특징 콜아웃", "review_quote": "후기 인용", "three_benefits": "혜택 3가지",
          "comparison": "비교표", "close_up": "클로즈업", "lifestyle": "사용 장면", "product_overlay": "상품 오버레이",
          "floating_product": "떠 있는 상품", "text_focus": "텍스트 집중", "demo": "시연", "result": "결과 강조", "cta": "구매 유도"}


@dataclass
class LayoutContext:
    photos: list[dict] = field(default_factory=list)       # identity.photos
    usage_path: str | None = None
    clip_paths: list[str] = field(default_factory=list)
    cutout_ok: set = field(default_factory=set)             # 배경 제거가 신뢰되는 사진 경로
    zoomable: set = field(default_factory=set)              # 확대해도 되는 사진 경로 (제품 위치 알고 해상도 충분)
    features: list[str] = field(default_factory=list)       # 사용자 입력 특징 (신뢰 A)
    review_quotes: list[str] = field(default_factory=list)  # 사용자가 준 실제 후기 문구
    before_after: tuple[str, str] | None = None             # (before 사진, after 사진)
    comparison: list[dict] | None = None                    # [{"label","ours","other"}] 사용자가 준 비교 데이터

    def box_known(self, path: str | None) -> bool:
        return any(p["path"] == path and p.get("focus") for p in self.photos)


def availability(layout: str, scene, ctx: LayoutContext) -> tuple[bool, str]:
    path = scene.visual_source.get("path")
    t = scene.scene_type
    if layout == "before_after":
        return bool(ctx.before_after), "전/후 사진이 없어서 사용 불가 (지어내지 않음)"
    if layout == "review_quote":
        return bool(ctx.review_quotes), "사용자가 준 후기 문구가 없어서 사용 불가"
    if layout == "comparison":
        return bool(ctx.comparison), "비교 데이터가 없어서 사용 불가"
    if layout == "three_benefits":
        return len(ctx.features) >= 2, "특징이 2개 미만"
    if layout == "demo":
        return bool(ctx.clip_paths), "실제 시연 영상이 없어서 사용 불가 (정지 사진을 '시연'이라고 표시하지 않음)"
    if layout == "lifestyle":
        return bool(ctx.clip_paths or ctx.usage_path), "사용 장면(영상/사용 사진)이 없어서 사용 불가"
    if layout == "close_up":
        return path in ctx.zoomable, "확대할 수 없는 사진 (해상도 부족/제품 위치 미상)"
    if layout == "feature_callout":
        return ctx.box_known(path), "제품 위치를 몰라 콜아웃을 못 가리킴"
    if layout == "problem_solution":
        return t == "PROBLEM", "문제 장면 전용"
    if layout == "cta":
        return t == "CTA", "CTA 전용"
    if layout == "result":
        return t in ("BENEFIT", "PRODUCT_REVEAL"), "혜택/공개 장면 전용"
    return True, ""


def _score(layout: str, scene, prev: str | None, used: dict, ctx: LayoutContext, next_is_cta: bool) -> float:
    base = FITNESS.get(scene.scene_type, {}).get(layout, 1.0)
    s = base - 3.0 * used.get(layout, 0)
    if prev and FAMILY[layout] == FAMILY[prev]:
        s -= 2.0                                       # 같은 계열 연속 = 슬라이드쇼 느낌
    if next_is_cta and FAMILY[layout] == "card":
        s -= 5.0                                       # CTA 직전엔 CTA(카드)와 다른 화면
    if layout in ("split_screen",) and len({p["path"] for p in ctx.photos}) < 2:
        s -= 1.5                                       # 같은 사진 두 번 = 새 장면 아님
    if layout == "floating_product" and scene.visual_source.get("path") not in ctx.cutout_ok:
        s -= 1.0
    return s


def _fill_data(layout: str, scene, ctx: LayoutContext, i: int, used_quotes: list) -> None:
    ld: dict = {}
    if layout == "feature_callout":
        ld["callout"] = (scene.emphasis[0] if scene.emphasis else scene.main_caption)
    elif layout == "three_benefits":
        ld["items"] = ctx.features[:3]
    elif layout == "review_quote":
        q = ctx.review_quotes[len(used_quotes) % len(ctx.review_quotes)]
        used_quotes.append(q)
        ld["quote"] = q
    elif layout == "before_after":
        ld["before"], ld["after"] = ctx.before_after
    elif layout == "comparison":
        ld["rows"] = ctx.comparison
    elif layout == "split_screen":
        others = [p["path"] for p in ctx.photos if p["path"] != scene.visual_source.get("path")]
        scene.secondary_source = others[i % len(others)] if others else scene.visual_source.get("path", "")
    scene.layout_data = ld


def select_layouts(scenes: list, ctx: LayoutContext) -> None:
    """scenes[i].layout 과 layout_data, decisions['layout'] 을 채운다 (결정적: 랜덤 없음)."""
    used: dict[str, int] = {}
    used_quotes: list = []
    prev: str | None = None
    n = len(scenes)
    for i, sc in enumerate(scenes):
        nxt_cta = i + 1 < n and scenes[i + 1].scene_type == "CTA"
        cands = []
        for l in LAYOUTS:
            ok, _ = availability(l, sc, ctx)
            if ok and l != prev and FITNESS.get(sc.scene_type, {}).get(l, 0) > 0:
                cands.append((_score(l, sc, prev, used, ctx, nxt_cta), -((LAYOUTS.index(l) - i) % len(LAYOUTS)), l))
        if not cands:                                   # 안전망: 어떤 장면도 비지 않게
            cands = [(0.0, 0, "product_center" if prev != "product_center" else "text_focus")]
        cands.sort(reverse=True)
        pick = cands[0][2]
        sc.layout = pick
        sc.decisions["layout"] = (f"{LABELS[pick]} ({cands[0][0]:.1f}점)" + " / 후보: " +
                                  ", ".join(f"{LABELS[c[2]]} {c[0]:.1f}" for c in cands[1:4]))
        used[pick] = used.get(pick, 0) + 1
        prev = pick
    _ensure_off_center(scenes, ctx, used)
    used_quotes.clear()
    for i, sc in enumerate(scenes):
        _fill_data(sc.layout, sc, ctx, i, used_quotes)


def _ensure_off_center(scenes: list, ctx: LayoutContext, used: dict) -> None:
    """상품이 항상 정중앙에만 있는 구성 금지: 4장면 이상이면 비중앙 레이아웃을 최소 1/3."""
    n = len(scenes)
    if n < 4:
        return
    need = math.ceil(n / 3)
    have = sum(1 for s in scenes if s.layout in OFF_CENTER)
    if have >= need:
        return
    swap_order = [i for i, s in enumerate(scenes) if s.scene_type not in ("HOOK", "CTA") and s.layout not in OFF_CENTER]
    for i in swap_order:
        if have >= need:
            break
        sc = scenes[i]
        prev = scenes[i - 1].layout if i else None
        nxt = scenes[i + 1].layout if i + 1 < n else None
        best = None
        for l in OFF_CENTER:
            ok, _ = availability(l, sc, ctx)
            if ok and l not in (prev, nxt) and FITNESS.get(sc.scene_type, {}).get(l, 0) > 0:
                sco = FITNESS[sc.scene_type][l] - 3.0 * used.get(l, 0)
                if best is None or sco > best[0]:
                    best = (sco, l)
        if best:
            used[sc.layout] -= 1
            sc.decisions["layout"] = sc.decisions.get("layout", "") + f" → 비중앙 구도 확보를 위해 {LABELS[best[1]]} 로 교체"
            sc.layout = best[1]
            used[best[1]] = used.get(best[1], 0) + 1
            have += 1
