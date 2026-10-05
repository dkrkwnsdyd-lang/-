"""PRODUCT INPUT / 사진 분석 / PRODUCT LOCK(제품 아이덴티티).

사진만 보고 판매량·리뷰수·효능·인증·특허를 만들어내지 않는다. 모르면 UNKNOWN.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageFilter, ImageOps

UNKNOWN = "UNKNOWN"


@dataclass
class ProductInput:
    name: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    problem: str = ""                 # 이 제품이 해결하는 불편 (사용자 입력)
    target: str = ""                  # 누가 쓰는지
    my_take: str = ""                 # 사용자가 직접 써본 느낌 한 줄 (실제 경험만). 문구에서 경험담으로 쓸 수 있는 유일한 근거
    price: str = ""
    price_meta: dict | None = None    # 가격 출처/조회 시각 {"source":"coupang_partners_api","fetched_at":ISO}. 24시간 지나면 사실 근거에서 제외
    url: str = ""
    photos: list[str] = field(default_factory=list)
    compact: bool = False             # 12~15초 압축 구조
    preview: bool = False             # True 면 장면 카드(Storyboard)와 썸네일까지만 만들고 MP4 는 만들지 않는다 (Preview Mode)
    director_data: dict | None = None  # Preview 에서 확정한 대본 (있으면 AI 대본 생성을 다시 하지 않는다)
    edits: dict | None = None         # Preview 에서 사용자가 수정한 내용 (storyboard/preview.py 참고)
    strategy: bool = True             # SHOPPING_SHORTS_STRATEGY_ENGINE (False 면 기존 director 로 대본 생성)
    video_style: str = "FAST_COMMERCE"  # FAST_COMMERCE | STORY_AD | UGC_REVIEW
    strategy_auto: bool = True        # AUTO 최적화: 전략 자동 선택 + Conversion Audit 자동 수정
    strategy_state: dict | None = None  # Preview 에서 확정한 전략 단계 결과 (재사용)
    strategy_force: bool = False      # Quality Gate 미통과여도 사용자가 확인하고 제작
    reference_patterns: list[str] = field(default_factory=list)   # Pattern Library id (REFERENCE_VIDEO_ENGINE): 구조만 적용, 내용 복사 없음
    reference_picks: dict | None = None                           # 영역별 수동 선택 {"hook": id, "story": id, "tempo": id, "cta": id} (없으면 AUTO MIX)
    ugc_session: str = ""             # UGC Reference Mode 세션 id (선택). 있으면 그 스토리보드/프롬프트 패키지로 대본·장면을 구성하고 기존 렌더/Preview 를 그대로 쓴다
    content_type: str = "PRODUCT"     # PRODUCT(상품 쇼츠) | DAILY(일상 속 상품: 일상 장면에 상품이 자연스럽게 나오는 쇼츠, 판매 전략 엔진 대신 일상 구성)
    daily_notes: list[str] = field(default_factory=list)   # 일상 장면 메모(장소/시간대, 사용자가 직접 입력한 것만 사용)
    highlight: bool = False           # 하이라이트 구간 자동 선택(동작/소리/제품·사용 신호, 선택·기본 OFF)
    polish: bool = False              # SNS 마감(시청 유지 리듬/진행 막대/실측 리포트, 선택·기본 OFF)
    flow3: bool = False               # 3-Scene Flow Mode (선택, 기본 OFF): AI_PRODUCT_UGC 장면에 Scene 1~3 프롬프트 적용
    scene_prompts: list[str] = field(default_factory=list)   # (내부) 장면별 AI 영상 프롬프트
    actor_mode: str = "AUTO"          # PRODUCT_ONLY | REAL_UGC | AI_PRESENTER | AI_PRODUCT_UGC | AUTO (presenter/modes.py)
    cost_mode: str = "BALANCED"       # ECONOMY | BALANCED | PREMIUM (AI 영상 길이 상한)
    monthly_budget: float | None = None  # 월 AI 예산(USD). 넘으면 비용 모드를 내린다. 결제는 하지 않는다
    generate_ai: bool = False         # True 일 때만 AI 영상 생성 API 를 호출한다 (비용 동의). 캐시된 결과는 동의 없이 재사용
    legacy_render: bool = False       # True 면 Storyboard 대신 기존 편집/렌더 경로 (비교 테스트/안전망)
    review_quotes: list[str] = field(default_factory=list)   # 사용자가 가진 실제 후기 문구 (review_quote 레이아웃, 없으면 사용 안 함)
    before_after: list[str] = field(default_factory=list)    # [전 사진, 후 사진] (before_after 레이아웃)
    comparison: list[dict] = field(default_factory=list)     # [{"label","ours","other"}] 사용자가 근거를 가진 비교 데이터
    enhance: bool = True              # PHOTO ENHANCEMENT V2 (False 면 원본 그대로: 비교 테스트용)
    videos: list[str] = field(default_factory=list)   # 직접 찍은 상품 영상 클립 (사용 장면용, 원본 소리는 쓰지 않음)
    photo_rights: str = "OWNED"       # OWNED | SELLER_PROVIDED | LICENSED | STOCK_LICENSED | UNKNOWN
    reference_url: str = ""
    affiliate: str = "NONE"           # NONE | COUPANG_PARTNERS | NAVER_SHOPPING_CONNECT | BRAND_SPONSORSHIP | OTHER_AFFILIATE
    category_hint: str = ""
    claim_sources: dict[str, str] = field(default_factory=dict)  # 주장 -> 근거(URL/문서)
    # 복잡한 배경 사진의 제품 위치 (파일명 -> [x0,y0,x1,y1], 0~1). 사용자 지정 또는 Vision LLM 이 채운다.
    product_boxes: dict[str, list[float]] = field(default_factory=dict)
    # 특징 문장 -> 그 특징이 보이는 사진 파일명. 없으면 사진을 순서대로 돌려 쓰므로 자막과 화면이 어긋날 수 있다.
    feature_photos: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ProductInput":
        d = dict(d)
        if isinstance(d.get("features"), str):
            d["features"] = [f.strip() for f in re.split(r"[\n,]", d["features"]) if f.strip()]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def text(self) -> str:
        return " ".join([self.name, self.description, " ".join(self.features), self.problem, self.category_hint])


# ------------------------------------------------------------------ URL import

def import_from_url(url: str, session: requests.Session | None = None) -> dict:
    """상품 페이지의 공개 메타데이터(og:*, JSON-LD Product)만 읽는다. 차단/로그인 우회는 하지 않는다.

    실패하면 {} 를 돌려주고, 호출자는 URL + 사진 + 수동 입력으로 진행한다.
    """
    session = session or requests.Session()
    try:
        resp = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 ShopShortsImporter"})
    except requests.RequestException:
        return {}
    if resp.status_code != 200:
        return {}
    html = resp.text
    out: dict = {}

    def meta(prop: str) -> str | None:
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)', html, re.I) \
            or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']', html, re.I)
        return m.group(1).strip() if m else None

    out["name"] = meta("og:title") or ""
    out["description"] = meta("og:description") or meta("description") or ""
    img = meta("og:image")
    out["images"] = [img] if img else []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Product":
                out["name"] = item.get("name") or out["name"]
                out["description"] = item.get("description") or out["description"]
                imgs = item.get("image")
                if imgs:
                    out["images"] = imgs if isinstance(imgs, list) else [imgs]
                offers = item.get("offers") or {}
                if isinstance(offers, dict) and offers.get("price"):
                    out["price"] = f"{offers.get('price')} {offers.get('priceCurrency', '')}".strip()
    return {k: v for k, v in out.items() if v}


# ------------------------------------------------------------------ photo analysis

@dataclass
class PhotoAnalysis:
    path: str
    width: int
    height: int
    sharpness: float
    brightness: float
    dominant_colors: list[str]
    background: str                   # plain | busy
    product_box: tuple[float, float, float, float]   # 0~1 (x0, y0, x1, y1)
    photo_angle: str = UNKNOWN
    quality_grade: str = "B"           # PHOTO QUALITY A(그대로)/B(보정 후)/C(품질 부족) - C 는 확대 컷에 쓰지 않는다
    product_category: str = UNKNOWN
    shape: str = UNKNOWN
    logo: str = UNKNOWN
    material: str = UNKNOWN
    visible_features: list[str] = field(default_factory=list)
    controls: str = UNKNOWN
    size_hint: str = UNKNOWN
    usage_hint: str = UNKNOWN
    cutout: dict = field(default_factory=dict)   # 배경 제거 신뢰도 (PRODUCT LOCK)
    focus: list[float] | None = None             # 제품 위치를 알 때만 (확대 컷 허용)
    box_source: str = ""                         # user | vision | auto
    analyzer: str = "pixel_stats_v1"


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


def sharpness_of(gray: np.ndarray) -> float:
    lap = (-4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:])
    return float(lap.var())


def product_mask(img: Image.Image, size: int = 256) -> tuple[np.ndarray, str]:
    """배경색과의 차이로 제품 영역 추정. (mask 0~1, 'plain'|'busy')"""
    small = ImageOps.contain(img.convert("RGB"), (size, size))
    a = np.asarray(small).astype(np.float32)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    border_spread = float(np.mean(np.linalg.norm(border - bg, axis=1)))
    dist = np.linalg.norm(a - bg, axis=2)
    thr = max(38.0, border_spread * 2.2)
    mask = (dist > thr).astype(np.float32)
    kind = "plain" if border_spread < 18 else "busy"
    return mask, kind


def analyze_photo(path: str | Path) -> PhotoAnalysis:
    with Image.open(path) as im:
        img = ImageOps.exif_transpose(im).convert("RGB")
    w, h = img.size
    gray = np.asarray(ImageOps.contain(img, (512, 512)).convert("L")).astype(np.float32)
    mask, kind = product_mask(img)
    ys, xs = np.nonzero(mask)
    if kind == "plain" and len(xs) > mask.size * 0.02:
        # 이상치 제거를 위해 백분위 사용
        x0, x1 = np.percentile(xs, [1, 99]) / mask.shape[1]
        y0, y1 = np.percentile(ys, [1, 99]) / mask.shape[0]
        box = (max(0, x0 - 0.02), max(0, y0 - 0.02), min(1, x1 + 0.02), min(1, y1 + 0.02))
    else:
        box = (0.08, 0.08, 0.92, 0.92)   # 배경이 복잡하면 중앙 대부분을 제품 영역으로 가정
    pal = ImageOps.contain(img, (96, 96)).quantize(colors=5, method=Image.Quantize.MEDIANCUT)
    counts = sorted(pal.getcolors(), reverse=True)
    palette = pal.getpalette()
    colors = [_hex(palette[i * 3:i * 3 + 3]) for _, i in counts[:4]]
    return PhotoAnalysis(str(path), w, h, round(sharpness_of(gray), 1), round(float(gray.mean()), 1),
                         colors, kind, tuple(round(float(v), 3) for v in box), cutout=cutout_reliability(img))


# ------------------------------------------------------------------ PRODUCT LOCK

@dataclass
class ProductIdentity:
    product_id: str
    name: str
    front_reference: str | None
    side_reference: str | None
    detail_reference: str | None
    usage_reference: str | None
    logo_reference: str | None
    color_reference: list[str]
    dimensions_hint: str
    distinctive_features: list[str]
    control_position: str
    photos: list[dict]
    missing_angles: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def lock_prompt(self) -> str:
        """영상 생성 provider 에 모든 장면마다 강제로 붙이는 제품 고정 조건."""
        feats = ", ".join(self.distinctive_features[:5]) or "as in reference photo"
        return (f"Exact same product as reference ({self.name}). Keep identical color {', '.join(self.color_reference[:3])}, "
                f"same logo, same button/control position ({self.control_position}), same proportions and shape. "
                f"Distinctive: {feats}. Do not redesign, recolor, or add parts.")


def build_identity(product: ProductInput, analyses: list[PhotoAnalysis], product_id: str) -> ProductIdentity:
    if not analyses:
        raise ValueError("제품 사진이 최소 1장 필요합니다 (PRODUCT LOCK)")

    def score_front(a: PhotoAnalysis) -> float:
        x0, y0, x1, y1 = a.product_box
        centered = 1 - abs((x0 + x1) / 2 - 0.5) - abs((y0 + y1) / 2 - 0.5)
        return min(a.sharpness, 400) / 400 + centered + (0.3 if a.background == "plain" else 0)

    ranked = sorted(analyses, key=score_front, reverse=True)
    front = ranked[0]
    detail = max(analyses, key=lambda a: a.sharpness * min(a.width, a.height))
    busy = [a for a in analyses if a.background == "busy"]
    usage = busy[0] if busy else None
    others = [a for a in ranked if a is not front]
    missing = [n for n, v in [("side", others), ("usage", usage)] if not v]
    return ProductIdentity(
        product_id=product_id,
        name=product.name or UNKNOWN,
        front_reference=front.path,
        side_reference=others[0].path if others else None,
        detail_reference=detail.path,
        usage_reference=usage.path if usage else None,
        logo_reference=None,
        color_reference=front.dominant_colors,
        dimensions_hint=UNKNOWN,
        distinctive_features=list(product.features),
        control_position=UNKNOWN,
        photos=[asdict(a) for a in analyses],
        missing_angles=missing,
    )


def cutout_reliability(img: Image.Image) -> dict:
    """배경 제거를 믿어도 되는지. 제품이 배경색과 비슷하면(흰 제품+흰 배경) 제품 일부가 지워져
    형태가 바뀌므로 PRODUCT LOCK 위반 -> 사용하지 않는다."""
    small = ImageOps.contain(img.convert("RGB"), (256, 256))
    a = np.asarray(small).astype(np.float32)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(a - bg, axis=2)
    mask, kind = product_mask(img)
    ys, xs = np.nonzero(mask)
    if kind != "plain" or len(xs) < mask.size * 0.02:
        return {"ok": False, "reason": "busy_or_empty"}
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    box = dist[y0:y1, x0:x1]
    ambiguous = float(((box > 8) & (box < 38)).mean())      # 배경과 애매하게 다른 픽셀 비율
    solidity = float(mask[y0:y1, x0:x1].mean())
    ok = ambiguous < 0.12 and solidity > 0.25
    return {"ok": ok, "ambiguous": round(ambiguous, 3), "solidity": round(solidity, 3),
            "reason": "" if ok else "low_contrast_product"}


def cutout(img: Image.Image, feather: float = 2.0) -> Image.Image | None:
    """단색 배경 제품 사진이면 배경을 투명하게 (RGBA). 복잡한 배경/신뢰 불가면 None."""
    from PIL import ImageDraw

    if not cutout_reliability(img)["ok"]:
        return None
    mask, kind = product_mask(img, size=512)
    if kind != "plain" or mask.mean() < 0.02 or mask.mean() > 0.9:
        return None
    small = Image.fromarray((mask * 255).astype(np.uint8))
    small = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    # 테두리에서 이어진 배경만 배경으로 본다 -> 제품 안쪽의 배경색 비슷한 부분(구멍)은 채워짐
    w, h = small.size
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
        if small.getpixel((x, y)) == 0:
            ImageDraw.floodfill(small, (x, y), 128)
    arr = np.asarray(small)
    filled = np.where(arr == 128, 0, 255).astype(np.uint8)
    m = Image.fromarray(filled).resize(img.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(feather))
    out = img.convert("RGBA")
    out.putalpha(m)
    return out
