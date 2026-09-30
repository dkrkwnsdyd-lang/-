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
from .director import ZOOM_SHOTS, zoomable
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
        if s.shot in ZOOM_SHOTS and not zoomable(identity, ref):
            issues.append("복잡한 배경 사진 - 제품 위치를 알 수 없어 확대 컷은 배경을 잡음 -> 히어로 계열로 교체")
            fixes["shot"] = "hero_push" if s.beat != "hook" else "punch_in"
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


COMMERCIAL_KEYS = ["lighting", "composition", "product_presentation", "background_cleanliness", "camera_feel",
                   "visual_variety", "real_ad_feeling", "amateur_look", "ai_look"]


def vision_review(router, images: list[str], context: str, frames_info: list[dict] | None = None) -> dict | None:
    """Vision LLM 이 있으면 프레임을 사람 눈 기준으로 검사. 없으면 None.
    frames_info[i] = {"caption","tts"}: i 번째 이미지에 표시되는 자막/대사 -> 장면-대본 일치를 판정한다."""
    if not router or not router.has_real("vision"):
        return None
    fails = brain.system("quality_rules")["visual_qa_fail"]
    system = ("You are a strict commercial video QA reviewer for short shopping videos made from REAL photos/clips of a product. "
              "You see N frames (one per cut, in order). Be honest: do not inflate scores. "
              "Scale (0-100, use consistently): 90-100 professional studio/advertising quality; "
              "75-89 clean, sharp, well-framed real product shots with tidy editing; "
              "60-74 acceptable but visibly amateur (harsh light, clutter, soft focus, awkward crop); "
              "40-59 poor (busy background, product hard to see, obvious phone snapshot); below 40 unusable. "
              "Judge frames (composition, sharpness, product visibility, lighting, text legibility, artifacts, "
              "product identity consistency across frames). Also judge whether each frame actually SHOWS what its caption/voice line says "
              "(e.g. caption says 'LED ring' but no LED ring is visible = mismatch). "
              "Failures to report if present: " + ", ".join(fails) + ". "
              "Answer JSON only: "
              '{"scores":{"visual":0,"product_accuracy":0,"ai_artifact":0,"commercial_feel":0,"scene_script_match":0},'
              '"commercial":{"lighting":0,"composition":0,"product_presentation":0,"background_cleanliness":0,"camera_feel":0,'
              '"visual_variety":0,"real_ad_feeling":0,"amateur_look":0,"ai_look":0},'
              '"frame_script":[{"frame":0,"match":0,"issue":""}],"distinct_scenes":0,'
              '"failures":[],"top_issues":["most damaging problem first, max 4, short Korean phrases"],'
              '"notes":"one or two short sentences saying what lowers the score"}. '
              "In commercial: every value is 0-100 where 100 = best; amateur_look 100 = looks professional, 0 = obviously amateur snapshot; "
              "ai_look 100 = looks like real footage/photos, 0 = obviously AI/synthetic; visual_variety = how different the frames are from each other; "
              "background_cleanliness 100 = clean uncluttered background. distinct_scenes = number of truly different scenes among the frames "
              "(the same photo with only a different zoom/crop counts as the same scene).")
    lines = []
    for i, info in enumerate((frames_info or [])[:len(images)]):
        cap, tts = (info.get("caption") or "").strip(), (info.get("tts") or "").strip()
        lines.append(f"frame {i}: caption='{cap}' voice='{tts}'")
    user = context + ("\n" + "\n".join(lines) if lines else "")
    try:
        v = router.run("vision", "json", system=system, user=user, images=images[:8], temperature=0).value
        return v if isinstance(v, dict) else {"error": "invalid response"}
    except Exception as e:  # QA 보조 단계 - 실패해도 로컬 QA 는 진행
        return {"error": str(e)[:200]}


def commercial_score(vision: dict | None) -> tuple[int | None, dict]:
    """Vision 의 9개 세부 점수 -> Commercial Feel (가중 평균; 최저값도 반영해 한 항목이 크게 낮으면 끌어내림)."""
    if not vision or vision.get("error"):
        return None, {}
    sub = vision.get("commercial") or {}
    w = brain.system("quality_rules")["final_qa_v2"]["commercial_weights"]
    vals = {k: float(sub[k]) for k in COMMERCIAL_KEYS if isinstance(sub.get(k), (int, float))}
    if len(vals) < 5:
        v = vision.get("scores", {}).get("commercial_feel")
        return (int(v) if isinstance(v, (int, float)) else None), vals
    avg = sum(vals[k] * w[k] for k in vals) / sum(w[k] for k in vals)
    score = 0.8 * avg + 0.2 * min(vals.values())
    return int(round(score)), {k: int(v) for k, v in vals.items()}


def scene_script_score(vision: dict | None) -> int | None:
    if not vision or vision.get("error"):
        return None
    fs = [f for f in (vision.get("frame_script") or []) if isinstance(f, dict) and isinstance(f.get("match"), (int, float))]
    if fs:
        m = [float(f["match"]) for f in fs]
        return int(round(0.7 * sum(m) / len(m) + 0.3 * min(m)))
    v = (vision.get("scores") or {}).get("scene_script_match")
    return int(v) if isinstance(v, (int, float)) else None


# ------------------------------------------------------------------ MULTI TAKE / BEST TAKE

def take_variants(scene, identity: ProductIdentity, n: int) -> list[dict]:
    """image motion 방식의 take 후보 (샷/구도/방향/참고 이미지 변형)."""
    options = [scene.shot] + [o for o in brain.system("scene_rules")["beat_to_shot"][scene.beat] if o != scene.shot]
    photos = [p["path"] for p in identity.photos]
    base = {"shot": scene.shot, "source": scene.reference_image, "zoom": (1.0, 1.08), "pan": (1.0, 0.0)}
    variants = [base]
    alt_shots = [o for o in options if o != scene.shot] + [scene.shot]
    alt_sources = [p for p in photos if p != scene.reference_image] + [scene.reference_image]
    fixed_src = (scene.beat in ("cta", "benefit") or scene.ref_locked) and scene.reference_image   # 사용 장면/연결된 사진 고정
    for i in range(1, n):
        src = fixed_src or alt_sources[(i - 1) % len(alt_sources)]
        pool = [x for x in alt_shots if x not in ZOOM_SHOTS or zoomable(identity, src)] or [scene.shot]
        variants.append({"shot": pool[(i - 1) % len(pool)],
                         "source": src,
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
             vision: dict | None = None, caption_scale: float = 1.0, photo_quality: dict | None = None) -> dict:
    th = brain.system("quality_rules")["final_qa_thresholds"]
    v2 = brain.system("quality_rules")["final_qa_v2"]
    pacing = brain.system("quality_rules")["pacing"]
    f3 = brain.system("quality_rules")["first_3_seconds"]
    cap_rules = brain.system("caption_rules")
    info = probe_video(video)
    frames = sample_frames(video)
    notes: dict[str, list[str]] = {k: [] for k in list(th) + list(v2["complete_thresholds"]) + ["visual_diversity", "commercial_feel", "scene_script_match", "product_accuracy"]}
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
    same = sum(1 for a, b in zip(edl["shots"], edl["shots"][1:]) if a.shot == b.shot and a.source == b.source and a.clip_start == b.clip_start)
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
                            if _similar(x, y) or (shots[i].shot == shots[i + 1].shot and shots[i].source == shots[i + 1].source and shots[i].clip_start == shots[i + 1].clip_start)})
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

    # --- DIVERSITY: 같은 제품 사진의 Zoom/Crop 만 바꾼 컷은 새 장면으로 100% 인정하지 않는다
    shots = edl["shots"]
    src_keys = [(s_.source, round(s_.clip_start, 1)) if s_.shot == "video_clip" else (s_.source, 0.0) for s_ in shots]
    unique_src = len(set(src_keys))
    n_cuts = max(1, len(shots))
    n_looks = looks if mids else unique_src
    credit = v2["repeat_same_source_credit"]
    effective = unique_src + credit * max(0, n_looks - unique_src)
    source_div = int(min(100, unique_src / max(2.0, n_cuts / 3) * 100))
    visual_div = int(min(100, effective / (v2["visual_diversity_target"] * n_cuts) * 100))
    if visual_div < 60:
        notes["visual_diversity"].append(f"서로 다른 원본 {unique_src}개 / 컷 {n_cuts}개 - 같은 사진의 확대·크롭 반복 (유효 장면 {effective:.1f})")

    # --- AI artifact (로컬: 원본 사진 모션은 생성 변형이 없음)
    artifact_local = 96 - (6 * len(low_res))

    # --- CTA
    cta = 100
    if not plan.scenes or plan.scenes[-1].beat != "cta":
        cta = 40; notes["cta"].append("CTA 없음")
    elif edl["shots"][-1].duration < 1.5:
        cta -= 20; notes["cta"].append("CTA 너무 짧음")

    # ============================== 점수 체계 ==============================
    # 1) LOCAL TECHNICAL SCORE: 측정 가능한 기술 항목 (예전 overall). 이것만 높다고 고품질로 판정하지 않는다.
    local = {"hook": hook, "visual_quality": visual, "product_consistency": product, "story": story, "pacing": pace,
             "caption": cap, "audio": audio, "ai_artifact": artifact_local, "cta": cta}
    local = {k: int(max(0, min(100, round(v)))) for k, v in local.items()}
    tw = {"hook": 1.4, "visual_quality": 1.2, "product_consistency": 1.3, "story": 1.0, "pacing": 1.0,
          "caption": 0.9, "audio": 0.6, "ai_artifact": 1.0, "cta": 0.6}
    technical = round(sum(local[k] * w for k, w in tw.items()) / sum(tw.values()))

    res = score_v2(local, technical, visual_div, source_div,
                   {"unique_sources": unique_src, "cuts": n_cuts, "effective_scenes": round(effective, 2)}, vision, photo_quality,
                   usage_missing=not any(s_.shot == "video_clip" for s_ in shots) and not getattr(identity, "usage_reference", None))
    scores, verdict, failed, blockers, gates, improvements = (res[k] for k in ("scores", "verdict", "failed", "blockers", "gates", "improvements"))
    have_vision, vision_quality, final, commercial, commercial_sub = (res[k] for k in ("have_vision", "vision_quality", "final", "commercial", "commercial_sub"))
    semantic_div = scores["semantic_diversity"]
    total = edl["total"]
    duration_issue = "short" if total < lo - 1 else "long" if total > hi + 2 else None
    return {"scores": scores, "passed": verdict == "COMPLETE", "verdict": verdict, "failed": failed, "blockers": blockers,
            "gates": gates, "improvements": improvements,
            "final_quality": {"technical": technical, "vision": vision_quality, "final": final, "verdict": verdict,
                              "have_vision": have_vision},
            "commercial": {"score": commercial, "sub": commercial_sub},
            "diversity": {"source": source_div, "visual": visual_div, "semantic": semantic_div, "unique_sources": unique_src,
                          "cuts": n_cuts, "distinct_looks": n_looks, "effective_scenes": round(effective, 2)},
            "repair_hints": {"repeat_scenes": repeat_scenes, "duration": duration_issue,
                             "low_res": bool(low_res), "monotone": bool(mids) and looks / len(mids) < 0.6},
            "notes": {k: v for k, v in notes.items() if v}, "video": info,
            "measured": {"sharpness": round(float(sharp), 1), "brightness": round(float(bright), 1),
                         "audio_mean_db": level, **timing},
            "vision": vision, "method": "local_metrics" + ("+vision_llm" if have_vision else "")}


def score_v2(local: dict, technical: int, visual_div: int, source_div: int, div_meta: dict, vision: dict | None,
             photo_quality: dict | None, usage_missing: bool) -> dict:
    """LOCAL TECHNICAL / VISION QUALITY / FINAL QUALITY 산출 + Hard Gate + 판정 + 개선 목록 (순수 함수: 테스트 가능).
    local: hook, visual_quality, product_consistency, story, pacing, caption, audio, ai_artifact, cta (0~100)."""
    v2 = brain.system("quality_rules")["final_qa_v2"]
    local = {**{"hook": 100, "story": 100, "pacing": 100, "caption": 100, "audio": 100, "cta": 100,
                "visual_quality": 100, "product_consistency": 100, "ai_artifact": 100}, **local}
    # 2) VISION QUALITY: Vision 이 본 것 (사람 눈 기준)
    have_vision = bool(vision and not vision.get("error") and vision.get("scores"))
    vs = (vision or {}).get("scores") or {}
    v_visual = vs.get("visual") if have_vision else None
    v_product = (vs.get("product_accuracy") if vs.get("product_accuracy") is not None else vs.get("product_consistency")) if have_vision else None
    v_artifact = vs.get("ai_artifact") if have_vision else None
    commercial, commercial_sub = commercial_score(vision) if have_vision else (None, {})
    ssm = scene_script_score(vision) if have_vision else None
    semantic_div = None
    if have_vision and isinstance(vision.get("distinct_scenes"), (int, float)) and vision.get("frame_script"):
        semantic_div = int(min(100, vision["distinct_scenes"] / max(1, len(vision["frame_script"])) * 100))

    # 최종 항목: 로컬 측정과 Vision 판단 중 더 나쁜 쪽 (제품/화질/아티팩트)
    final_items = {
        "visual_quality": min(x for x in (local["visual_quality"], v_visual) if x is not None),
        "product_accuracy": min(x for x in (local["product_consistency"], v_product) if x is not None),
        "ai_artifact": min(x for x in (local["ai_artifact"], v_artifact) if x is not None),
        "commercial_feel": commercial, "scene_script_match": ssm,
        "pacing": local["pacing"], "hook": local["hook"], "story": local["story"], "caption": local["caption"],
        "visual_diversity": visual_div,
    }
    final_items = {k: (int(v) if v is not None else None) for k, v in final_items.items()}
    vision_parts = [final_items[k] for k in ("visual_quality", "product_accuracy", "ai_artifact", "commercial_feel", "scene_script_match")
                    if final_items[k] is not None] if have_vision else []
    vision_quality = int(round(sum(vision_parts) / len(vision_parts))) if vision_parts else None

    # 3) FINAL QUALITY: 핵심 항목 가중 평균 -> 최약 핵심 항목 + margin 상한 -> Hard Gate
    cw = v2["core_weights"]
    present = {k: v for k, v in final_items.items() if v is not None}
    avg = sum(present[k] * cw[k] for k in present) / sum(cw[k] for k in present)
    crit = [present[k] for k in v2["critical"] if k in present]
    weakest = min(crit) if crit else 100
    final = min(avg, weakest + v2["weakest_link_margin"])
    g = v2["gates"]
    gates: list[dict] = []
    blockers: list[str] = []

    def gate(name: str, hit: bool, effect: str) -> None:
        gates.append({"gate": name, "hit": hit, "effect": effect if hit else "-"})

    fv, fc, fa, fp, fs = (final_items[k] for k in ("visual_quality", "commercial_feel", "ai_artifact", "product_accuracy", "scene_script_match"))
    hit = fv is not None and fv < g["visual_cap"]["below"]
    gate(f"Visual < {g['visual_cap']['below']}", hit, f"최종 점수 최대 {g['visual_cap']['max_final']}")
    if hit:
        final = min(final, g["visual_cap"]["max_final"])
    hit = fa is not None and fa < g["ai_artifact_cap"]["below"]
    gate(f"AI Artifact < {g['ai_artifact_cap']['below']}", hit, f"최종 점수 최대 {g['ai_artifact_cap']['max_final']}")
    if hit:
        final = min(final, g["ai_artifact_cap"]["max_final"])
    hit = fp is not None and fp < g["product_accuracy_block"]
    gate(f"Product Accuracy < {g['product_accuracy_block']}", hit, "COMPLETE 금지")
    if hit:
        blockers.append(f"Product Accuracy {fp}")
    hit = fs is not None and fs < g["scene_script_block"]
    gate(f"Scene-Script Match < {g['scene_script_block']}", hit, "COMPLETE 금지")
    if hit:
        blockers.append(f"Scene-Script Match {fs}")
    both_low = fv is not None and fc is not None and fv < g["visual_and_commercial_fail"] and fc < g["visual_and_commercial_fail"]
    gate(f"Visual·Commercial 둘 다 < {g['visual_and_commercial_fail']}", both_low, "QUALITY_FAIL")
    if both_low:
        blockers.append(f"Visual {fv} + Commercial {fc}")
    if not have_vision:
        final = min(final, g["no_vision_cap"])
        gate("Vision 평가 없음", True, f"최종 점수 최대 {g['no_vision_cap']}, NEEDS_REVIEW (로컬 기술 점수만으로 고품질 판정 안 함)")
    final = int(round(final))

    # 개별 기준 미달 목록 (수리 루프가 사용하는 키 이름 유지)
    ct = v2["complete_thresholds"]
    key_map = {"visual_quality": "visual_quality", "product_accuracy": "product_consistency", "ai_artifact": "ai_artifact"}
    failed = []
    for k in ("visual_quality", "product_accuracy", "commercial_feel", "ai_artifact", "scene_script_match", "hook", "story", "pacing",
              "caption", "visual_diversity"):
        v = final_items.get(k)
        if v is not None and v < ct[k]:
            failed.append(key_map.get(k, k))
    for k in ("audio", "cta"):
        if local[k] < ct[k]:
            failed.append(k)
    if final < ct["final"]:
        failed.append("overall")
    vision_fail = [f for f in (vision or {}).get("failures", []) if f] if have_vision else []
    if vision_fail:
        failed.append("visual_qa_fail")
        blockers.append("Vision 실패 항목: " + ", ".join(map(str, vision_fail)))
    if not have_vision:
        # 최종 점수는 Vision 부재로 상한(79)이 걸려 있으므로 'overall 미달'은 판정 근거에서 제외
        verdict = "QUALITY_FAIL" if ([f for f in failed if f != "overall"] or blockers) else "NEEDS_REVIEW"
    else:
        verdict = "COMPLETE" if not failed and not blockers else "QUALITY_FAIL"

    scores = {**local, "technical": technical, "vision_quality": vision_quality, "overall": final, "final": final,
              "product_accuracy": final_items["product_accuracy"], "commercial_feel": commercial,
              "scene_script_match": ssm, "visual_diversity": visual_div, "source_diversity": source_div,
              "semantic_diversity": semantic_div}
    scores["visual_quality"] = final_items["visual_quality"]
    scores["ai_artifact"] = final_items["ai_artifact"]
    scores = {k: (int(max(0, min(100, round(v)))) if v is not None else None) for k, v in scores.items()}

    # 개선 필요 목록: 가장 큰 실패 원인부터
    improvements = _improvements(scores, ct, photo_quality, vision, commercial_sub, have_vision, div_meta["unique_sources"], div_meta["cuts"], div_meta["effective_scenes"],
                                 usage_missing=usage_missing)
    return {"scores": scores, "verdict": verdict, "failed": failed, "blockers": blockers, "gates": gates,
            "improvements": improvements, "have_vision": have_vision, "vision_quality": vision_quality, "final": final,
            "commercial_sub": commercial_sub, "commercial": commercial, "technical": technical}


def _improvements(scores: dict, ct: dict, photo_quality: dict | None, vision: dict | None, commercial_sub: dict,
                  have_vision: bool, unique_src: int, n_cuts: int, effective: float, usage_missing: bool) -> list[dict]:
    """사용자에게 보여줄 '개선 필요' 목록 (원인 + 조치). deficit 이 큰 순."""
    items: list[tuple[float, dict]] = []

    def add(deficit: float, cause: str, detail: str, action: str) -> None:
        items.append((deficit, {"cause": cause, "detail": detail, "action": action}))

    if photo_quality:
        ph = photo_quality.get("photos", [])
        bad = [p for p in ph if p["grade_before"] != "A" and p["reasons"]]
        if bad:
            reasons = sorted({r.split(" (")[0] for p in bad for r in p["reasons"]})
            worst = 40 if any(p["grade_before"] == "C" for p in bad) else 22
            add(worst, "원본 사진 품질 부족", ", ".join(reasons[:4]), "밝은 자연광에서 단색 배경으로 다시 촬영 (제품이 화면의 60~80%)")
    if usage_missing:
        add(30, "실제 사용 장면 없음", "사진 모션만으로 구성됨", "사용 장면 영상(3~10초) 또는 사용 중인 사진 추가")
    vd = scores.get("visual_diversity")
    if vd is not None and vd < ct["visual_diversity"] + 15:
        add(max(10, 85 - vd), "같은 제품 이미지 반복", f"서로 다른 원본 {unique_src}개 / 컷 {n_cuts}개 (유효 장면 {effective:.1f})",
            "각도·배경이 다른 사진/영상을 더 추가하거나 컷 수를 줄여 짧게")
    cf = scores.get("commercial_feel")
    if cf is not None and cf < ct["commercial_feel"]:
        weak = sorted(commercial_sub.items(), key=lambda kv: kv[1])[:3]
        names = {"lighting": "조명", "composition": "구도", "product_presentation": "제품 연출", "background_cleanliness": "배경 정리",
                 "camera_feel": "카메라 느낌", "visual_variety": "화면 다양성", "real_ad_feeling": "실제 광고 느낌",
                 "amateur_look": "아마추어 느낌", "ai_look": "AI 느낌"}
        add(ct["commercial_feel"] - cf + 8, "Commercial Feel 부족", ", ".join(f"{names.get(k, k)} {v}" for k, v in weak), "조명/배경 정리, 사용 장면 촬영")
    if scores.get("visual_quality") is not None and scores["visual_quality"] < ct["visual_quality"]:
        add(ct["visual_quality"] - scores["visual_quality"] + 5, "화면 품질 부족", f"Visual {scores['visual_quality']}", "선명하고 밝은 원본 사진 사용")
    ssm = scores.get("scene_script_match")
    if ssm is not None and ssm < ct["scene_script_match"]:
        bad = [f for f in (vision or {}).get("frame_script", []) if isinstance(f, dict) and f.get("issue")][:2]
        add(ct["scene_script_match"] - ssm + 6, "장면과 자막이 안 맞음", "; ".join(str(f["issue"]) for f in bad) or f"일치도 {ssm}",
            "자막이 말하는 것이 보이는 사진을 연결하거나 자막을 수정")
    if scores.get("product_accuracy") is not None and scores["product_accuracy"] < ct["product_accuracy"]:
        add(ct["product_accuracy"] - scores["product_accuracy"] + 10, "제품 정확도 부족", f"Product Accuracy {scores['product_accuracy']}", "제품이 잘 보이는 사진으로 교체")
    if scores.get("ai_artifact") is not None and scores["ai_artifact"] < ct["ai_artifact"]:
        add(ct["ai_artifact"] - scores["ai_artifact"] + 4, "AI/합성 느낌", f"AI Artifact {scores['ai_artifact']}", "저해상도 확대를 줄이고 원본 화질을 높임")
    for issue in (vision or {}).get("top_issues", [])[:4] if have_vision else []:
        if isinstance(issue, str) and issue.strip():
            add(6, "Vision 지적", issue.strip(), "")
    if not have_vision:
        add(50, "Vision 평가 없음", "로컬 기술 점수만 있음", "Gemini 등 Vision 키를 연결해 사람 눈 기준 평가")
    items.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, it in items:
        key = it["cause"] if it["cause"] != "Vision 지적" else it["detail"]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:6]
