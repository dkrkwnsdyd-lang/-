"""VISUAL QA(스토리보드) / BEST TAKE SELECTOR / FINAL VIDEO QA.

로컬 QA 는 측정 가능한 지표(해상도, 선명도, 노출, 컷 타이밍, 자막, 오디오)로 채점한다.
Vision LLM 이 연결되어 있으면 샘플 프레임에 대한 사람 눈 기준 평가를 추가한다.
점수는 '느낌'이 아니라 근거(reason)와 함께 기록한다.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .. import brain
from ..video import ffmpeg_exe
from .product import ProductIdentity, sharpness_of

# ------------------------------------------------------------------ frame metrics


def _gray(img: Image.Image, size=(270, 480)) -> np.ndarray:
    return np.asarray(img.convert("L").resize(size, Image.BILINEAR)).astype(np.float32)


def frame_metrics(frames: list[Image.Image], caption_zone: str = "top") -> dict:
    gs = [_gray(f) for f in frames]
    sharp = float(np.mean([sharpness_of(g) for g in gs]))
    bright = float(np.mean([g.mean() for g in gs]))
    motion = float(np.mean([np.abs(a - b).mean() for a, b in zip(gs, gs[1:])])) if len(gs) > 1 else 0.0
    g = gs[len(gs) // 2]
    gy, gx = np.gradient(g)
    e = np.hypot(gx, gy)
    h = e.shape[0]
    center = e[int(h * 0.3):int(h * 0.8), int(e.shape[1] * 0.15):int(e.shape[1] * 0.85)].sum()
    band = e[int(h * 0.12):int(h * 0.3)] if caption_zone == "top" else e[int(h * 0.62):int(h * 0.78)]
    return {"sharpness": round(sharp, 1), "brightness": round(bright, 1), "motion": round(motion, 2),
            "center_focus": round(float(center / (e.sum() + 1e-6)), 3),
            "caption_band_busy": round(float(band.mean()), 2)}


# ------------------------------------------------------------------ VISUAL QA (storyboard)

def storyboard_qa(scenes, identity: ProductIdentity) -> list[dict]:
    """장면별 참고 이미지 검사. 원본 제품 사진만 쓰므로 제품 변형 항목은 구조적으로 발생하지 않는다."""
    q = brain.system("quality_rules")["source_image"]
    photos = {p["path"]: p for p in identity.photos}
    results = []
    for s in scenes:
        ref = s.reference_image
        issues, fixes = [], {}
        ph = photos.get(ref)
        if ref is None or ph is None:
            issues.append("reference_image 가 제품 아이덴티티에 없는 이미지")
            results.append({"scene_id": s.scene_id, "pass": False, "issues": issues, "scores": {}, "fix": {}})
            continue
        short = min(ph["width"], ph["height"])
        scores = {
            "product_accuracy": 100, "product_consistency": 100,   # 원본 사진 모션 (생성 X)
            "hand_quality": None, "face_quality": None,           # 사람 장면 없음
            "scene_relevance": 90 if s.beat != "problem" else 70,
            "composition": 85,
            "lighting": 90 if q["exposure"][0] <= ph["brightness"] <= q["exposure"][1] else 60,
            "commercial_quality": 80 if ph["background"] == "plain" else 70,
            "ai_artifact": 100, "text_artifact": 100, "background_error": 100,
        }
        if short < q["min_short_side"]:
            issues.append(f"해상도 부족 ({ph['width']}x{ph['height']})")
            scores["commercial_quality"] -= 20
        if ph["sharpness"] < q["min_sharpness"]:
            issues.append(f"흐림 (sharpness {ph['sharpness']})")
            scores["commercial_quality"] -= 15
        # 매크로는 원본에서 잘라 쓰므로 고해상도가 필요
        if s.shot in ("macro", "detail_pan") and short < 1000:
            issues.append("매크로 샷에 원본 해상도 부족 -> 히어로 샷으로 교체")
            fixes["shot"] = "hero_push" if s.beat != "hook" else "punch_in"
        if ph.get("cutout", {}).get("reason") == "low_contrast_product":
            issues.append("제품이 배경색과 비슷해 배경 제거 안 함 (형태 보존) -> 원본 카드 방식")
        if s.beat == "benefit" and ph["background"] == "plain" and identity.usage_reference is None:
            issues.append("사용 장면(라이프스타일) 사진 없음 - 스튜디오 컷으로 대체")
        fail_flags = [k for k in brain.system("quality_rules")["visual_qa_fail"] if k in " ".join(issues)]
        results.append({"scene_id": s.scene_id, "pass": not fail_flags and short >= q["min_short_side"] * 0.6,
                        "issues": issues, "scores": scores, "fix": fixes})
    return results


def vision_review(router, images: list[str], context: str) -> dict | None:
    """Vision LLM 이 있으면 프레임을 사람 눈 기준으로 검사. 없으면 None."""
    if not router or not router.has_real("vision"):
        return None
    fails = brain.system("quality_rules")["visual_qa_fail"]
    system = ("You are a strict commercial video QA reviewer. Score 0-100 and list any of these failures: "
              + ", ".join(fails) + '. Answer JSON: {"scores":{"visual":0,"product_consistency":0,"ai_artifact":0,'
              '"commercial_feel":0},"failures":[],"notes":""}')
    try:
        return router.run("vision", "json", system=system, user=context, images=images[:6]).value
    except Exception as e:  # QA 보조 단계 - 실패해도 로컬 QA 는 진행
        return {"error": str(e)[:200]}


# ------------------------------------------------------------------ MULTI TAKE / BEST TAKE

def take_variants(scene, identity: ProductIdentity, n: int) -> list[dict]:
    """image motion 방식의 take 후보 (샷/구도/방향/참고 이미지 변형)."""
    options = [scene.shot] + [o for o in brain.system("scene_rules")["beat_to_shot"][scene.beat] if o != scene.shot]
    photos = [p["path"] for p in identity.photos]
    base = {"shot": scene.shot, "source": scene.reference_image, "zoom": (1.0, 1.08), "pan": (1.0, 0.0)}
    variants = [base]
    alt_shots = [o for o in options if o != scene.shot] + [scene.shot]
    alt_sources = [p for p in photos if p != scene.reference_image] + [scene.reference_image]
    for i in range(1, n):
        variants.append({"shot": alt_shots[(i - 1) % len(alt_shots)],
                         "source": alt_sources[(i - 1) % len(alt_sources)] if scene.beat not in ("cta",) else scene.reference_image,
                         "zoom": (1.0, 1.12) if i % 2 else (1.06, 1.0), "pan": (-1.0 if i % 2 else 1.0, 0.0)})
    return variants[:n]


def score_take(renderer, scene, variant: dict, story_options: list[str]) -> dict:
    from .motion import Shot
    shot = Shot(scene.scene_id, variant["shot"], variant["source"], max(scene.duration, 1.0),
                zoom=variant["zoom"], pan=variant["pan"], grade="problem" if scene.beat == "problem" else "normal")
    frames = [renderer.frame(shot, shot.duration * k, 0) for k in (0.05, 0.5, 0.95)]
    m = frame_metrics(frames)
    motion_q = 100 - min(100, abs(m["motion"] - 6.0) * 9)          # 너무 정적/너무 요란 모두 감점
    visibility = min(100, m["center_focus"] * 160)
    sharp_q = min(100, m["sharpness"] / 3.0)
    story = 100 if variant["shot"] == story_options[0] else 80 if variant["shot"] in story_options else 60
    caption_q = max(0, 100 - m["caption_band_busy"] * 4)
    scores = {
        "motion_quality": round(motion_q), "product_accuracy": 100, "product_visibility": round(visibility),
        "human_quality": None, "camera_quality": round(0.5 * motion_q + 0.5 * sharp_q),
        "story_match": story, "commercial_quality": round(0.6 * sharp_q + 0.4 * caption_q), "artifact_score": 100,
    }
    w = {"story_match": 2.0, "product_visibility": 1.5}
    vals = [(v, w.get(k, 1.0)) for k, v in scores.items() if v is not None]
    total = round(sum(v * k for v, k in vals) / sum(k for _, k in vals))
    return {"variant": variant, "metrics": m, "scores": scores, "total": total}


def best_take(renderer, scene, identity: ProductIdentity) -> dict:
    # 디렉터가 고른 샷을 스토리 적합도 1순위로
    options = [scene.shot] + [o for o in brain.system("scene_rules")["beat_to_shot"][scene.beat] if o != scene.shot]
    takes = [score_take(renderer, scene, v, options) for v in take_variants(scene, identity, max(1, scene.takes))]
    for i, t in enumerate(takes):
        t["name"] = "ABC"[i] if i < 3 else str(i)
    best = max(takes, key=lambda t: t["total"])
    others = [t for t in takes if t is not best]
    reason = f"{best['name']} 선택 (총점 {best['total']})"
    if others:
        diffs = []
        for k in ("product_visibility", "motion_quality", "commercial_quality", "story_match"):
            d = best["scores"][k] - max(o["scores"][k] for o in others)
            if d > 0:
                diffs.append(f"{k} +{d}")
        reason += ": " + (", ".join(diffs) if diffs else "종합 점수 우위")
    return {"scene_id": scene.scene_id, "takes": [{k: v for k, v in t.items() if k != "variant"} | {"shot": t["variant"]["shot"]}
                                                   for t in takes],
            "selected": best["name"], "reason": reason, "params": best["variant"]}


# ------------------------------------------------------------------ FINAL VIDEO QA

def probe_video(path: Path) -> dict:
    err = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    size = re.search(r"Video: .*?(\d{3,5})x(\d{3,5})", err)
    return {"duration": int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else 0,
            "width": int(size[1]) if size else 0, "height": int(size[2]) if size else 0,
            "has_audio": "Audio:" in err}


def sample_frames(path: Path, fps: float = 5, size=(180, 320)) -> list[np.ndarray]:
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={size[0]}:{size[1]}",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (size[0] * size[1])
    return [np.frombuffer(raw[i * size[0] * size[1]:(i + 1) * size[0] * size[1]], np.uint8)
            .reshape(size[1], size[0]).astype(np.float32) for i in range(n)]


def audio_level(path: Path) -> float:
    err = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return float(m.group(1)) if m else -99.0


def _small(f: np.ndarray) -> np.ndarray:
    img = Image.fromarray(f.astype(np.uint8)).resize((24, 42), Image.BILINEAR)
    a = np.asarray(img).astype(np.float32)
    # 자막 영역(상단)은 제외하고 비교
    a = a[int(42 * 0.32):]
    return (a - a.mean()) / (a.std() + 1e-6)


def _similar(a: np.ndarray, b: np.ndarray, thr: float = 0.93) -> bool:
    x, y = _small(a), _small(b)
    return float((x * y).mean()) > thr


def _distinct_looks(frames: list[np.ndarray]) -> int:
    reps: list[np.ndarray] = []
    for f in frames:
        if not any(_similar(f, r) for r in reps):
            reps.append(f)
    return len(reps)


def final_qa(video: Path, plan, edl: dict, has_voice: bool, font_ok: bool, identity: ProductIdentity,
             vision: dict | None = None, caption_scale: float = 1.0) -> dict:
    th = brain.system("quality_rules")["final_qa_thresholds"]
    pacing = brain.system("quality_rules")["pacing"]
    f3 = brain.system("quality_rules")["first_3_seconds"]
    cap_rules = brain.system("caption_rules")
    info = probe_video(video)
    frames = sample_frames(video)
    notes: dict[str, list[str]] = {k: [] for k in th}
    timing = edl["timing"]

    # --- hook
    hook = 100
    diffs = [float(np.abs(a - b).mean()) for a, b in zip(frames, frames[1:])]
    if not diffs or diffs[0] < 0.4:
        hook -= 15; notes["hook"].append("0초 움직임 약함")
    fc = timing["first_caption"]
    if fc is None or fc > f3["first_caption"][1] + 0.1:
        hook -= 15; notes["hook"].append(f"첫 자막 늦음 ({fc})")
    fv = timing["first_visual_change"]
    if fv is None or not (f3["first_visual_change"][0] - 0.1 <= fv <= f3["first_visual_change"][1] + 0.2):
        hook -= 15; notes["hook"].append(f"첫 화면 변화 시점 {fv}s (권장 0.8~1.3)")
    if plan.hook_type in ("unknown",):
        hook -= 10
    ra = timing["reveal_at"]
    if ra is not None and ra > 4.5:
        hook -= 10; notes["hook"].append(f"제품 공개 늦음 ({ra}s)")

    # --- visual
    sharp = np.mean([sharpness_of(f) for f in frames]) if frames else 0
    bright = np.mean([f.mean() for f in frames]) if frames else 0
    visual = 100
    if sharp < 60:
        visual -= min(30, (60 - sharp) / 2); notes["visual_quality"].append(f"선명도 낮음 ({sharp:.0f})")
    if not (40 <= bright <= 215):
        visual -= 15; notes["visual_quality"].append(f"노출 이상 ({bright:.0f})")
    black = sum(1 for f in frames if f.mean() < 8)
    if black:
        visual -= 10 * black; notes["visual_quality"].append(f"검은 프레임 {black}개")
    low_res = [p for p in identity.photos if min(p["width"], p["height"]) < 900]
    if low_res:
        visual -= 8 * len(low_res); notes["visual_quality"].append(f"저해상도 원본 {len(low_res)}장 (확대 시 흐려짐)")
    if info["width"] != 1080 or info["height"] != 1920:
        visual -= 20; notes["visual_quality"].append(f"해상도 {info['width']}x{info['height']}")

    # --- product consistency (원본 사진 모션: 모든 샷 소스가 아이덴티티 사진인지)
    allowed = {p["path"] for p in identity.photos}
    foreign = [s.source for s in edl["shots"] if s.source not in allowed]
    product = 100 - 30 * len(foreign)
    if foreign:
        notes["product_consistency"].append("아이덴티티 밖 이미지 사용")

    # --- story
    pat = brain.system("story_patterns")["patterns"].get(plan.story_pattern, {})
    beats = [s.beat for s in plan.scenes]
    story = 100
    for need in ("hook", "reveal", "cta"):
        if need not in beats:
            story -= 20; notes["story"].append(f"{need} 없음")
    if not any(b in beats for b in ("demo", "detail", "benefit")):
        story -= 20; notes["story"].append("증명/디테일 장면 없음")
    if pat and ra is not None and not (pat["reveal_at"][0] - 0.5 <= ra <= pat["reveal_at"][1] + 1.0):
        story -= 10; notes["story"].append(f"공개 시점 {ra}s 가 {plan.story_pattern} 권장 {pat['reveal_at']} 밖")
    if beats and beats[-1] != "cta":
        story -= 10

    # --- pacing
    pace = 100
    avg = timing["avg_shot"]
    if not (pacing["avg_shot_length"][0] <= avg <= pacing["avg_shot_length"][1]):
        pace -= 20; notes["pacing"].append(f"평균 컷 {avg}s")
    if timing["max_shot"] > pacing["max_shot_length"]:
        pace -= 15; notes["pacing"].append(f"최장 컷 {timing['max_shot']}s")
    same = sum(1 for a, b in zip(edl["shots"], edl["shots"][1:]) if a.shot == b.shot and a.source == b.source)
    if same:
        pace -= 10 * same; notes["pacing"].append(f"같은 구도 연속 {same}회")
    # 실제 화면 기준 반복 검사: 컷마다 중간 프레임을 비교 (샷 이름이 달라도 화면이 같으면 반복)
    mids = []
    bounds = timing["cuts"] + [edl["total"]]
    for a, b in zip(bounds, bounds[1:]):
        idx = min(len(frames) - 1, int((a + b) / 2 * 5))
        if frames:
            mids.append(frames[idx])
    looks = _distinct_looks(mids)
    shots = edl["shots"]
    repeat_scenes = sorted({shots[i + 1].scene_id for i, (x, y) in enumerate(zip(mids, mids[1:]))
                            if _similar(x, y) or (shots[i].shot == shots[i + 1].shot and shots[i].source == shots[i + 1].source)})
    repeats = sum(1 for x, y in zip(mids, mids[1:]) if _similar(x, y))
    if repeats:
        pace -= 8 * repeats; notes["pacing"].append(f"연속 컷 화면이 거의 같음 {repeats}회")
        visual -= 4 * repeats
    if mids and looks / len(mids) < 0.6:
        visual -= 12; notes["visual_quality"].append(f"서로 다른 화면 {looks}종 / 컷 {len(mids)}개 (단조로움)")
    early_cuts = sum(1 for c in timing["cuts"] if 0 < c <= 3.0)
    if early_cuts < 2:
        pace -= 10; notes["pacing"].append("첫 3초 편집 밀도 부족")
    lo, hi = plan.target_duration
    if not (lo - 1 <= edl["total"] <= hi + 2):
        pace -= 10; notes["pacing"].append(f"길이 {edl['total']}s (목표 {lo}~{hi})")

    # --- caption
    cap = 100
    if not font_ok:
        cap -= 40; notes["caption"].append("한글 자막 폰트 없음")
    for s in plan.scenes:
        lines = s.caption.replace("[[", "").replace("]]", "").split("\n")
        if len(lines) > cap_rules["max_lines"] or max(len(l) for l in lines) > cap_rules["max_chars_per_line"] + 3:
            cap -= 6; notes["caption"].append(f"{s.scene_id} 자막 김")
    if caption_scale < 0.8:
        cap -= round((0.8 - caption_scale) * 100); notes["caption"].append(f"자막이 길어 글자 크기 {caption_scale:.0%}로 축소됨")
    em = sum(1 for s in plan.scenes if "[[" in s.caption)
    if em < len(plan.scenes) / 2:
        cap -= 10; notes["caption"].append("강조 단어 부족")

    # --- audio
    level = audio_level(video) if info["has_audio"] else -99
    audio = 100
    if not info["has_audio"] or level < -45:
        audio = 30; notes["audio"].append("오디오 없음/무음")
    if not has_voice:
        audio -= 20; notes["audio"].append("보이스오버 없음 (TTS provider 미연결) - 음악+효과음만")

    # --- AI artifact (원본 사진 모션은 생성 변형이 없음)
    artifact = 96 - (6 * len(low_res))
    if vision and vision.get("scores"):
        artifact = min(artifact, vision["scores"].get("ai_artifact", artifact))
        visual = min(visual, vision["scores"].get("visual", visual))

    # --- CTA
    cta = 100
    if not plan.scenes or plan.scenes[-1].beat != "cta":
        cta = 40; notes["cta"].append("CTA 없음")
    elif edl["shots"][-1].duration < 1.5:
        cta -= 20; notes["cta"].append("CTA 너무 짧음")

    scores = {"hook": hook, "visual_quality": visual, "product_consistency": product, "story": story,
              "pacing": pace, "caption": cap, "audio": audio, "ai_artifact": artifact, "cta": cta}
    scores = {k: int(max(0, min(100, round(v)))) for k, v in scores.items()}
    weights = {"hook": 1.4, "visual_quality": 1.2, "product_consistency": 1.3, "story": 1.0, "pacing": 1.0,
               "caption": 0.9, "audio": 0.6, "ai_artifact": 1.0, "cta": 0.6}
    overall = round(sum(scores[k] * w for k, w in weights.items()) / sum(weights.values()))
    scores["overall"] = overall
    failed = [k for k, v in scores.items() if v < th.get(k, 0)]
    total = edl["total"]
    duration_issue = "short" if total < lo - 1 else "long" if total > hi + 2 else None
    return {"scores": scores, "passed": not failed, "failed": failed,
            "repair_hints": {"repeat_scenes": repeat_scenes, "duration": duration_issue,
                             "low_res": bool(low_res), "monotone": bool(mids) and looks / len(mids) < 0.6},
            "notes": {k: v for k, v in notes.items() if v}, "video": info,
            "measured": {"sharpness": round(float(sharp), 1), "brightness": round(float(bright), 1),
                         "audio_mean_db": level, **timing},
            "vision": vision, "method": "local_metrics" + ("+vision_llm" if vision and vision.get("scores") else "")}
