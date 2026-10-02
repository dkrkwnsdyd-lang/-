"""SHOP SHORTS V2 파이프라인 오케스트레이션 (JOB QUEUE 단계 기록, 장면 재시도, 최종 QA 수리 루프).

RENDER SUCCESS != COMPLETE.  QUALITY PASS = COMPLETE.
"""
from __future__ import annotations

import json
import shutil
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

import requests
from PIL import Image

from .. import brain
from ..db import DB
from ..providers import Router
from . import adapter, compliance
from .audio import build_mix
from .director import BEAT_DURATION, direct_scenes, llm_director, rule_director, zoomable
from .editor import edit, edl_summary, time_words
from .motion import MotionRenderer, caption_font_path
from . import clips as clips_mod
from . import enhance as enhance_mod
from .storyboard import build_storyboard, preview as preview_mod
from .storyboard.engine import layout_context
from .storyboard_edit import edit_from_storyboard
from . import strategy as strategy_mod
from . import presenter as presenter_mod
from .presenter import cost as cost_mod, generate as gen_mod
from .presenter.providers import default_providers
from .product import ProductInput, analyze_photo, build_identity, import_from_url
from .qa import best_take, final_qa, storyboard_qa, vision_review
from . import vision as vision_mod
from .reference import analyze_reference, learn
from .tts import synthesize

STEPS = ["PRODUCT_ANALYSIS", "REFERENCE_ANALYSIS", "SCRIPT", "STORYBOARD", "IMAGE_QA", "VIDEO_GEN",
         "VIDEO_QA", "EDIT", "RENDER", "FINAL_QA", "COMPLIANCE"]


class Job:
    def __init__(self, db: DB, job_id: str, progress_cb=None):
        self.db, self.id = db, job_id
        self.progress_cb = progress_cb
        self.log: list[str] = []

    def step(self, name: str):
        job = self

        class _Ctx:
            def __enter__(self_):
                job.db.step(job.id, name, "RUNNING")
                job.say(f"{name} 시작")
                return self_

            def __exit__(self_, et, ev, tb):
                if et is None:
                    job.db.step(job.id, name, "SUCCESS")
                else:
                    job.db.step(job.id, name, "FAILED", f"{et.__name__}: {ev}")
                    job.say(f"{name} 실패: {ev}")
                return False
        return _Ctx()

    def say(self, msg: str) -> None:
        self.log.append(msg)
        if self.progress_cb:
            self.progress_cb(msg)


def video_route(scene, router: Router, mode: str) -> dict:
    """VIDEO ROUTER: 장면 성격에 따라 provider 선택. 검증된 생성 provider 가 없으면 image motion."""
    critical = scene.beat in ("reveal", "demo", "detail", "cta")
    need = ["first_last_frame"] if critical else ["image_to_video"]
    cands = [m for m in router.candidates("video", need)]
    real = [m for m in cands if m.provider != "local"]
    if mode == "FAST" or not real:
        return {"provider": "local", "model": "image_motion_v2",
                "reason": "FAST 저비용" if mode == "FAST" else "검증된 영상 생성 provider 없음 -> High Quality Image Motion (제품 변형 0)"}
    best = real[0]
    return {"provider": best.provider, "model": best.model,
            "reason": "제품 일관성 중요 장면 -> first/end frame 지원 모델" if critical else "기본 영상 provider"}


ALT_SHOTS = ["macro", "detail_pan", "parallax", "light_sweep", "hero_push", "rack_focus"]


def _repair(plan, qa: dict, identity=None) -> list[str]:
    """최종 QA 실패 원인 -> 해당 장면만 수정 (전체 재생성 X)."""
    actions = []
    failed = set(qa["failed"])
    hints = qa.get("repair_hints", {})
    photos = [p["path"] for p in identity.photos] if identity else []
    # 반복/단조로움: 문제 장면만 다른 샷(가능하면 다른 사진)으로
    if hints.get("repeat_scenes") or hints.get("monotone"):
        targets = list(hints.get("repeat_scenes") or [])
        if hints.get("monotone") and not targets:
            targets = [s.scene_id for s in plan.scenes if s.beat not in ("hook", "cta")][1::2]
        used = [s.shot for s in plan.scenes]
        # 저해상도 원본이면 확대 샷(macro/detail_pan)은 후보에서 제외 -> 수리 결과가 서로 되돌리지 않게
        no_zoom = hints.get("low_res") or (identity is not None and not any(zoomable(identity, ph) for ph in photos))
        pool = [x for x in ALT_SHOTS if not (no_zoom and x in ("macro", "detail_pan"))]
        for sid in targets:
            sc = next((s for s in plan.scenes if s.scene_id == sid), None)
            if not sc or sc.beat == "cta":
                continue
            cands = [x for x in pool if x != sc.shot]
            new = min(cands, key=lambda x: (used.count(x), pool.index(x)))
            actions.append(f"{sid} 반복 화면 -> {sc.shot} 를 {new} 로")
            sc.shot = new
            used.append(new)
            if len(photos) > 1 and sc.reference_image in photos and sc.beat != "benefit" and not sc.ref_locked:
                sc.reference_image = photos[(photos.index(sc.reference_image) + 1) % len(photos)]
    # 길이
    lo, hi = plan.target_duration
    if hints.get("duration") == "short":
        post = [s for s in plan.scenes if s.beat not in ("hook", "problem")]
        need = lo - plan.duration + 0.6
        for s in post:
            s.duration = round(s.duration + need / len(post), 2)
        actions.append(f"길이 부족 -> 공개 이후 장면 +{need:.1f}s 분배")
    elif hints.get("duration") == "long" or ("pacing" in failed and not hints.get("repeat_scenes")):
        for s in plan.scenes:
            lo_b, hi_b = BEAT_DURATION[s.beat]
            if s.duration > hi_b:
                s.duration = round(hi_b, 2)
                actions.append(f"{s.scene_id} 길이 {hi_b}s 로 단축")
    if "hook" in failed and plan.scenes:
        h = plan.scenes[0]
        if h.shot not in ("punch_in", "macro"):
            h.shot = "punch_in"
            actions.append("S1 훅 샷을 punch_in 으로 교체")
    if "caption" in failed:
        rules = brain.system("caption_rules")
        for s in plan.scenes:
            lines = s.caption.split("\n")[:rules["max_lines"]]
            plain = [l.replace("[[", "").replace("]]", "") for l in lines]
            if max(len(l) for l in plain) > rules["max_chars_per_line"]:
                keep = [l for l in lines if "[[" in l] or lines[:1]
                s.caption = keep[0]
                actions.append(f"{s.scene_id} 자막 축약: {keep[0]}")
    if hints.get("low_res"):
        for s in plan.scenes:
            if s.shot in ("macro", "detail_pan"):
                s.shot = "hero_push"
                actions.append(f"{s.scene_id} 저해상도 원본 매크로 -> 히어로")
    return actions


def contact_sheet(renderer: MotionRenderer, shots, out: Path) -> Path:
    thumbs = []
    for i, s in enumerate(shots):
        thumbs.append(renderer.frame(s, s.duration * 0.6, i).resize((216, 384)))
    cols = min(len(thumbs), 8)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 216 + (cols + 1) * 8, rows * 384 + (rows + 1) * 8), (20, 20, 22))
    for i, t in enumerate(thumbs):
        sheet.paste(t, (8 + (i % cols) * 224, 8 + (i // cols) * 392))
    sheet.save(out, quality=88)
    return out


class StrategyBlocked(Exception):
    def __init__(self, gate: dict):
        super().__init__("strategy quality gate")
        self.gate = gate


def sctx_category(p) -> str:
    from .strategy.common import category_key
    return category_key(p.text())


def _pick_bgm(inputs: dict, p, category: str, result: dict) -> dict | None:
    """사용자가 곡을 직접 지정했으면 그것, 아니면(auto_bgm 이 꺼져 있지 않을 때) 음악 폴더 색인에서 카테고리/스타일에 맞는 곡. 없으면 내장 음악."""
    from . import bgm as bgm_mod
    if inputs.get("bgm_path"):
        result["music"] = {"source": "user", "file": Path(inputs["bgm_path"]).name}
        return {"path": inputs["bgm_path"]}
    if inputs.get("auto_bgm") is False:
        return None
    tracks = bgm_mod.load_index()
    t = bgm_mod.choose(tracks, category, p.video_style, seed=p.name or "") if tracks else None
    if not t or not Path(t["path"]).exists():
        result["music"] = {"source": "builtin", "note": "음악 폴더 색인이 없거나 맞는 곡이 없어 내장 음악 사용"}
        return None
    result["music"] = {"source": "library", "file": t["file"], "category": t["category"], "reason": t["reason"]}
    return {"path": t["path"]}


def _preview_result(renderer, sb, edl, identity, ctx, out_dir: Path) -> dict:
    """장면 카드용 썸네일(장면 중간 프레임)과 사진 목록, 장면별 선택지."""
    pdir = out_dir / "preview"
    pdir.mkdir(exist_ok=True)
    thumbs = {}
    for i, sh in enumerate(edl["shots"]):
        fp = pdir / f"{sh.scene_id}.jpg"
        renderer.frame(sh, sh.duration * 0.6, i).resize((270, 480)).save(fp, quality=85)
        thumbs[sh.scene_id] = str(fp)
    photos = []
    for i, ph in enumerate(identity.photos):
        fp = pdir / f"photo_{i}.jpg"
        with Image.open(ph["path"]) as im:
            im = im.convert("RGB")
            im.thumbnail((240, 240))
            im.save(fp, quality=80)
        photos.append({"index": i, "file": str(fp)})
    return {"preview": {"thumbs": thumbs, "photos": photos,
                        "options": {s.scene_id: preview_mod.options_for(s, ctx) for s in sb.scenes}}}


def run_job(inputs: dict, mode: str = "PRO", platforms: list[str] | None = None, out_root: str | Path = "output/v2",
            db: DB | None = None, router: Router | None = None, progress_cb=None, job_id: str | None = None,
            render: tuple[int, int, int] = (1080, 1920, 30), ai_providers: list | None = None) -> dict:
    mode = mode.upper()
    platforms = platforms or ["youtube", "instagram", "tiktok", "threads"]
    db = db or DB()
    job_id = job_id or uuid.uuid4().hex[:10]
    out_dir = Path(out_root) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    router = router or Router(db=db, job_id=job_id)
    router.db, router.job_id = db, job_id
    job = Job(db, job_id, progress_cb)
    p = ProductInput.from_dict(inputs)
    db.create_job(job_id, mode, p.name, inputs)
    db.update_job(job_id, "RUNNING")
    result: dict = {"job_id": job_id, "mode": mode, "status": "RUNNING"}
    core = brain.system("core_rules")
    try:
        # 1 PRODUCT INTELLIGENCE ------------------------------------------------
        with job.step("PRODUCT_ANALYSIS"):
            if p.url:
                imported = import_from_url(p.url)
                result["import"] = {"ok": bool(imported), "fields": sorted(imported)}
                p.name = p.name or imported.get("name", "")
                p.description = p.description or imported.get("description", "")
                p.price = p.price or imported.get("price", "")
                if not p.photos:
                    for i, u in enumerate(imported.get("images", [])[:4]):
                        try:
                            r = requests.get(u, timeout=15)
                            if r.status_code == 200:
                                dst = out_dir / f"import_{i}.jpg"
                                dst.write_bytes(r.content)
                                p.photos.append(str(dst))
                                p.photo_rights = "UNKNOWN"
                        except requests.RequestException:
                            pass
            if not p.photos:
                raise ValueError("제품 사진이 필요합니다 (URL 에서 이미지를 가져오지 못했으면 사진을 올려주세요)")
            src_dir = out_dir / "src"
            src_dir.mkdir(exist_ok=True)
            photos = []
            for i, ph in enumerate(p.photos):
                dst = src_dir / f"photo_{i}{Path(ph).suffix.lower() or '.jpg'}"
                shutil.copy(ph, dst)
                photos.append(str(dst))
                db.add_asset(job_id, str(dst), "product_photo", p.photo_rights, ph)
            src_copies = list(photos)          # ORIGINAL (덮어쓰지 않음)
            video_paths = []
            for i, vd in enumerate(p.videos):
                dst = src_dir / f"clip_{i}{Path(vd).suffix.lower() or '.mp4'}"
                shutil.copy(vd, dst)
                video_paths.append(str(dst))
                db.add_asset(job_id, str(dst), "product_video", p.photo_rights, vd)
            # PHOTO ENHANCEMENT V2: ORIGINAL(src/)은 그대로, 보정본은 enhanced/, 비교 자료는 derived/
            originals = list(photos)
            user_boxes = {photos[i]: tuple(p.product_boxes[Path(o).name]) for i, o in enumerate(p.photos)
                          if Path(o).name in p.product_boxes and len(p.product_boxes[Path(o).name]) == 4}
            if p.enhance:
                enh = enhance_mod.process_photos(photos, out_dir, router if mode == "PRO" else None, boxes=user_boxes)
                photos = list(enh["effective"])
                for orig_path, eff, item in zip(originals, photos, enh["photos"]):
                    if eff != orig_path:
                        db.add_asset(job_id, eff, "product_photo_enhanced", p.photo_rights, orig_path)
                result["photo_quality"] = {"summary": enh["summary"], "photos": [
                    {k: v for k, v in it.items() if k not in ("attempts",)} for it in enh["photos"]]}
                grades = [it["grade_after"] for it in enh["photos"]]
                good = [i for i, g in enumerate(grades) if g != "C"]
                if len(good) >= 2 and len(good) < len(photos):
                    dropped = [i for i in range(len(photos)) if i not in good]
                    for i in dropped:
                        result.setdefault("warnings", []).append(f"사진 {i + 1}: 품질 부족(C) - 영상에서 제외 ({'; '.join(enh['photos'][i]['reasons'][:2])})")
                    photos = [photos[i] for i in good]
                    originals = [originals[i] for i in good]
                    enh["photos"] = [enh["photos"][i] for i in good]
                elif any(g == "C" for g in grades):
                    result.setdefault("warnings", []).append("품질 부족(C) 사진뿐이라 그대로 사용합니다. 확대 컷은 쓰지 않으며 결과 품질이 낮을 수 있어요")
                for i, it in enumerate(enh["photos"]):
                    if it["grade_before"] != "A" and it["reasons"]:
                        result.setdefault("photo_notes", []).append(f"사진 {i + 1} [{it['grade_before']}]: " + "; ".join(it["reasons"][:3]))
                path_map = dict(zip(originals, photos))
            else:
                enh = None
                path_map = {o: o for o in photos}
            analyses = [analyze_photo(ph) for ph in photos]
            if enh:
                for a, it in zip(analyses, enh["photos"]):
                    a.quality_grade = it["grade_after"]
            saved_by_name = {Path(orig).name: path_map[c] for orig, c in zip(p.photos, src_copies) if c in path_map}
            name_by_eff = {v: k for k, v in saved_by_name.items()}
            p.feature_photos = {feat: saved_by_name[name] for feat, name in p.feature_photos.items()
                                if name in saved_by_name and feat in p.features}
            for a in analyses:
                box = p.product_boxes.get(name_by_eff.get(a.path, ""))
                if box and len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1:
                    a.product_box = tuple(box)
                    a.focus = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
                    a.box_source = "user"
            # Vision LLM: 사용자가 지정하지 않은 제품 위치/특징-사진 연결을 자동으로 채운다 (실패해도 계속)
            tight_paths: set[str] = set()
            vis = vision_mod.analyze(router, photos, p.features, out_dir / "vision")
            result["vision"] = vis
            if vis and not vis.get("error"):
                for idx, box in vis["boxes"].items():
                    if not analyses[idx].focus:      # 사용자 지정 우선
                        analyses[idx].product_box = tuple(box)
                        analyses[idx].focus = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
                        analyses[idx].box_source = "vision"
                for feat, idx in vis["feature_links"].items():
                    p.feature_photos.setdefault(feat, photos[idx])
                privacy = sorted({t for ph in vis["photos"] for t in ph["private_info_visible"]})
                if privacy:
                    result.setdefault("warnings", []).append("사진에 개인 정보로 보이는 요소: " + ", ".join(privacy))
                # 개인 정보가 찍힌 사진은 제품 위치를 알 때만, 그리고 제품 주변만 타이트하게 쓴다.
                private_idx = {ph["index"] for ph in vis["photos"] if ph["private_info_visible"]}
                private_paths = {photos[i] for i in private_idx}
                drop = [i for i in sorted(private_idx) if not analyses[i].focus]
                for i in drop:
                    result["warnings"].append(f"사진 {i + 1}: 개인 정보가 있고 제품 위치를 알 수 없어 영상에서 제외")
                if drop:
                    keep = [i for i in range(len(photos)) if i not in drop]
                    if not keep:
                        raise ValueError("모든 사진에 개인 정보가 있고 제품 위치를 알 수 없습니다. 제품 위치를 지정해 주세요.")
                    dropped_paths = {photos[i] for i in drop}
                    photos = [photos[i] for i in keep]
                    analyses = [analyses[i] for i in keep]
                    p.feature_photos = {f: pth for f, pth in p.feature_photos.items() if pth not in dropped_paths}
                tight_paths = private_paths & set(photos)
            elif vis and vis.get("error"):
                job.say("Vision 분석 실패 - 수동 입력값으로 진행: " + vis["error"][:120])
            identity = build_identity(p, analyses, product_id=f"P-{job_id}")
            if not p.name:
                p.name = "이 제품"
                job.say("상품명이 없어 '이 제품'으로 진행 (사진만으로 이름/효능을 추정하지 않음)")
            result["identity"] = identity.to_dict()

        # 2 REFERENCE -----------------------------------------------------------
        if p.reference_url:
            with job.step("REFERENCE_ANALYSIS"):
                ref = analyze_reference(p.reference_url, router)
                db.execute("INSERT INTO references_ (url, status, analysis_json, timestamp) VALUES (?,?,?,datetime('now'))",
                           (p.reference_url, ref["status"], json.dumps(ref, ensure_ascii=False)))
                ref["learned"] = learn(ref, brain.LearnedKnowledge(db.path.parent)) \
                    if ref["status"] != "UNVERIFIED" else False
                result["reference"] = ref

        # 3 STORY / SCRIPT / SCENES -------------------------------------------
        # 소스가 적으면(사진 2장 이하, 영상 없음) 억지로 늘리지 않고 12~15초 압축 구조로
        if not getattr(p, "compact", False) and len(photos) <= 2 and not video_paths:
            p.compact = True
            result.setdefault("warnings", []).append("원본 사진이 2장 이하라 같은 사진을 반복하지 않도록 12~15초로 짧게 만들었어요")
        with job.step("SCRIPT"):
            pattern_guide = None
            if p.reference_patterns:      # REFERENCE_VIDEO_ENGINE: 라이브러리 패턴(들)을 섞어 현재 상품용 연출 가이드로 (내용 복사 없음, 구조만)
                from .reference_engine import build_guide, library as ref_lib, mix as ref_mix
                recs = ref_lib.get_many(db, p.reference_patterns)
                if recs:
                    ctx0 = strategy_mod.make_ctx(p, p.video_style, mode, identity, result.get("vision"), has_clip=bool(video_paths))
                    pattern_guide = build_guide(ref_mix.mix(recs, ctx0, p.reference_picks), ctx0)
                    result["reference_guide"] = {k: v for k, v in pattern_guide.items() if k != "fingerprint"}
                else:
                    result.setdefault("warnings", []).append("선택한 Reference 패턴을 찾을 수 없어 기본 구성으로 만들었어요")
            sctx = strategy_mod.make_ctx(p, p.video_style, mode, identity, result.get("vision"), has_clip=bool(video_paths),
                                         reference=result.get("reference"), pattern=pattern_guide)
            if p.director_data:        # Preview 에서 확인한 대본을 그대로 쓴다 (AI 가 다시 쓰면 확인한 내용이 달라짐)
                data = dict(p.director_data)
                if p.strategy_state:
                    result["strategy"] = p.strategy_state
            elif p.strategy:           # SHOPPING_SHORTS_STRATEGY_ENGINE: 무엇을/누구에게/왜 팔지 정한 뒤 Hook -> 대본 -> 댓글 -> CTA -> 점검 -> 자동 수정
                with job.step("STRATEGY"):
                    state = strategy_mod.run_strategy(router, sctx, state=p.strategy_state, auto=p.strategy_auto, progress=job.say)
                    data = strategy_mod.to_director_data(sctx, state)
                    result["strategy"] = state
                    result["director_data"] = data
                    if not state["gate"]["passed"] and not p.preview and not p.strategy_force:
                        raise StrategyBlocked(state["gate"])
            else:
                data = llm_director(router, p, identity, mode, result.get("vision")) if router.has_real("llm") else rule_director(p, mode)
            if "_director" not in data:
                data["_director"] = "local:rule_director_v1"
            plan = direct_scenes(data, identity, p, mode)
            plan_edits = preview_mod.apply_plan_edits(plan, p.edits)
            if p.preview:
                result["director_data"] = data
            result["plan"] = plan.to_dict()
            result["grounding"] = {"script": data.get("_grounding")}

        renderer = MotionRenderer(width=render[0], height=render[1], fps=render[2])
        renderer.cache.boxes = {ph["path"]: tuple(ph["product_box"]) for ph in identity.photos if ph.get("focus")}
        by_eff = {it["effective"]: it for it in (enh or {}).get("photos", [])}
        renderer.cache.spot = {ph["path"] for ph in identity.photos if ph.get("focus")
                               and by_eff.get(ph["path"], {}).get("metrics_after", {}).get("background_complexity", 0) > 0.35}
        renderer.cache.tight = set(tight_paths)   # 개인 정보가 있는 사진은 제품 주변만 (넓게 자르지 않음)
        # 4 STORYBOARD + VISUAL QA (+ scene retry) ------------------------------
        with job.step("STORYBOARD"):
            sb = storyboard_qa(plan.scenes, identity)
            for attempt in range(core["retry"]["MAX_SCENE_RETRY"]):
                fixes = [r for r in sb if r["fix"]]
                if not fixes:
                    break
                for r in fixes:
                    sc = next(s for s in plan.scenes if s.scene_id == r["scene_id"])
                    sc.shot = r["fix"].get("shot", sc.shot)
                    db.step(job_id, "IMAGE_QA", "RUNNING", attempt=attempt + 1)
                    db.step(job_id, "IMAGE_QA", "RETRY", f"{sc.scene_id}: {r['issues']}")
                sb = storyboard_qa(plan.scenes, identity)
                for r in sb:
                    r["fix"] = {}
            for r in sb:
                db.add_qa(job_id, "storyboard", r["scene_id"], r["scores"], r["pass"], "; ".join(r["issues"]))
            result["storyboard_qa"] = sb
        with job.step("IMAGE_QA"):
            bad = [r for r in sb if not r["pass"]]
            if bad and len(bad) == len(sb):
                raise RuntimeError("모든 장면이 Visual QA 실패 - 더 선명한/큰 제품 사진이 필요합니다")

        # 5 VIDEO ROUTER + MULTI TAKE + BEST TAKE -------------------------------
        with job.step("VIDEO_GEN"):
            routes, takes_report, takes = {}, [], {}
            for s in plan.scenes:
                route = video_route(s, router, mode)
                if route["provider"] != "local":
                    # 생성 provider adapter 는 아직 검증 전 -> 제품 변형 없는 image motion 으로 폴백 (NEXT_TASKS 4)
                    route["used"] = "local:image_motion_v2"
                    route["reason"] += " / adapter 미검증으로 image motion 폴백"
                else:
                    route["used"] = "local:image_motion_v2"
                routes[s.scene_id] = route
                if mode == "FAST":
                    s.takes = 1
                bt = best_take(renderer, s, identity)
                takes_report.append(bt)
                takes[s.scene_id] = bt["params"]
                s.shot = bt["params"]["shot"]
                s.reference_image = bt["params"]["source"]
            result["routes"] = routes
            result["takes"] = takes_report
        with job.step("VIDEO_QA"):
            for bt in takes_report:
                best = next(t for t in bt["takes"] if t["name"] == bt["selected"])
                db.add_qa(job_id, "take", bt["scene_id"], best["scores"], best["total"] >= 60, bt["reason"])

        # 5-B VIDEO CLIPS (사용자가 찍은 영상 클립: 좋은 구간 분석 + 개인정보 검사) ---------------
        clip_infos: list[dict] = []
        if video_paths:
            with job.step("CLIPS"):
                clip_infos, cw = clips_mod.prepare(video_paths, out_dir / "clips_work")
                result.setdefault("warnings", []).extend(cw)
                screened, unchecked = [], False
                for info in clip_infos:
                    vis_c = vision_mod.analyze(router, clips_mod.sample_frames(info, out_dir / "clips_frames"), [],
                                               out_dir / "clips_vision")
                    if vis_c and not vis_c.get("error"):
                        priv = sorted({t for ph in vis_c["photos"] for t in ph["private_info_visible"]})
                        if priv:
                            result["warnings"].append(f"영상 {info['index'] + 1}: 개인 정보로 보이는 요소({', '.join(priv)})가 있어 제외")
                            continue
                    else:
                        unchecked = True
                    screened.append(info)
                clip_infos = screened
                if unchecked and clip_infos:
                    result["warnings"].append("영상 속 개인 정보(얼굴/번호판/주소 등)를 자동으로 검사하지 못했어요. 게시 전에 직접 확인하세요.")
                job.say(f"영상 클립 {len(clip_infos)}/{len(video_paths)}개 사용 가능")

        # 6 TTS -----------------------------------------------------------------
        voice = {}
        if router.has_real("tts") and not p.preview:       # 미리보기는 음성 비용/시간을 쓰지 않는다
            with job.step("TTS"):
                voice = synthesize(router, plan.scenes, out_dir / "tts")
        label = "광고" if p.affiliate != "NONE" else ""

        # 7 EDIT -> RENDER -> FINAL QA (repair loop) ---------------------------
        max_final = 0 if mode == "FAST" else core["retry"]["MAX_FINAL_RETRY"]
        history = []
        profiles = adapter.profiles()
        for version in range(1, max_final + 2):
            renderer.captions.last_scale = 1.0
            renderer.captions.cache.clear()
            with job.step("STORYBOARD_V2"):
                # Script -> Storyboard(JSON). 지금은 연출 결정을 '기록'만 하고 렌더링은 기존 경로 (Layout/Motion 연결은 다음 단계)
                cutout_ok = {ph["path"] for ph in identity.photos if renderer.cache.cutout(ph["path"]) is not None}
                # 출연 방식/비용 모드: 업로드 영상은 REAL_UGC/AUTO 에서만 쓴다. 월 예산을 넘으면 비용 모드를 내린다 (결제는 하지 않음)
                actor_mode = p.actor_mode if p.actor_mode in presenter_mod.ACTOR_MODES else "AUTO"
                cost_mode, budget_info = cost_mod.apply_budget(p.cost_mode if p.cost_mode in cost_mod.COST_MODES else "BALANCED", p.monthly_budget, db)
                use_infos = clip_infos if presenter_mod.uses_real_clips(actor_mode) else []
                clip_paths = [c["path"] for c in use_infos]
                ref_photo = identity.photos[0]["path"] if identity.photos else None
                sb = build_storyboard(plan, identity, p, result.get("vision"), clip_paths, style=p.video_style, mode=mode, cutout_ok=cutout_ok, pattern_guide=pattern_guide,
                                      post_layout=lambda scs: presenter_mod.plan_production(
                                          scs, ctx=sctx, actor_mode=actor_mode, cost_mode=cost_mode, style=p.video_style, infos=use_infos, router=router,
                                          work_dir=out_dir / "real", reference_image=ref_photo))
                sb.production["budget"] = budget_info
                if sb.production.get("reference"):
                    result["reference_application"] = sb.production["reference"]
                lctx = layout_context(identity, p, clip_paths, cutout_ok)
                sb_edits = preview_mod.apply_sb_edits(sb, p.edits, lctx, identity, [f for f in p.features if f])
                if result.get("strategy"):
                    strategy_mod.annotate_storyboard(sb, result["strategy"])
                    result["strategy"]["final_storyboard"] = strategy_mod.final_storyboard_view(sb)
                    strategy_mod.save_state(out_dir, result["strategy"])
                if p.edits:
                    result["edits_report"] = {k: plan_edits[k] + sb_edits[k] for k in ("applied", "rejected")}
                # AI 장면: 캐시는 동의 없이 재사용, 새 생성(비용)은 generate_ai 동의가 있을 때만. 실패/불일치는 원본으로 대체
                provs = ai_providers if ai_providers is not None else default_providers()
                if any(sc.ai for sc in sb.scenes):
                    (out_dir / "ai").mkdir(exist_ok=True)
                    gen = gen_mod.run_generation(sb.scenes, ctx=sctx, db=db, job_id=job_id, providers=provs, vision_router=router,
                                                 cost_mode=sb.production.get("cost_mode", "BALANCED"), actor_mode=actor_mode,
                                                 consent=bool(p.generate_ai), work_dir=out_dir / "ai")
                    result["ai_generation"] = gen
                    if not p.preview:
                        gen_mod.finalize_fallbacks(sb.scenes)
                    sb.production["estimate"] = gen_mod.estimate_for(sb.scenes, provs, sb.production.get("cost_mode", "BALANCED"))
                    sb.total_duration = round(sum(sc.duration for sc in sb.scenes), 2)
                sb.production["ai_summary"] = gen_mod.summarize(sb.scenes)
                (out_dir / f"v{version}").mkdir(exist_ok=True)
                (out_dir / f"v{version}" / "storyboard.json").write_text(sb.to_json(), encoding="utf-8")
                result["storyboard"] = sb.to_dict()
            with job.step("EDIT"):
                if p.legacy_render:
                    edl = edit(plan, takes, voice, label=label,
                               zoomable_paths={ph['path'] for ph in identity.photos if zoomable(identity, ph['path'])})
                else:      # Storyboard(JSON) -> EDL -> Renderer. AI 와 Renderer 는 Storyboard 로만 연결된다
                    edl = edit_from_storyboard(sb, voice, label=label)
            clip_report = clips_mod.assign(edl["shots"], plan.scenes, use_infos) if not p.legacy_render else clips_mod.assign(edl["shots"], plan.scenes, clip_infos)
            if video_paths:
                result["clips"] = {"provided": len(video_paths), "usable": len(clip_infos), "used": (sb.production.get("real_scenes") or []) + clip_report}
            if p.preview:
                result.update(_preview_result(renderer, sb, edl, identity, lctx, out_dir))
                result["preview"]["providers"] = [{"name": pv.name, "available": pv.available(), "verified": pv.verified, "mock": pv.mock,
                                                   "configured": pv.configured(), "capabilities": list(pv.capabilities)} for pv in provs]
                renderer.close_clips()
                result["status"] = "PREVIEW_READY"
                result["log"] = job.log
                db.update_job(job_id, "PREVIEW_READY", result)
                (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                return result
            with job.step("RENDER"):
                body = [s for s in edl["shots"] if s.scene_id != plan.scenes[-1].scene_id]
                cta = [s for s in edl["shots"] if s.scene_id == plan.scenes[-1].scene_id]
                vdir = out_dir / f"v{version}"
                vdir.mkdir(exist_ok=True)
                body_mp4 = renderer.render(body, vdir / "body.mp4",
                                           progress_cb=lambda f: job.progress_cb and job.progress_cb(f"렌더 {f:.0%}"))
                cta_mp4 = renderer.render(cta, vdir / "cta_master.mp4")
                video_only = adapter.concat([body_mp4, cta_mp4], vdir / "master_video.mp4")
                bgm_choice = _pick_bgm(inputs, p, sctx_category(p), result)
                mix = build_mix(edl["total"], edl["events"], edl["voice"], vdir / "mix.wav",
                                bgm_path=bgm_choice["path"] if bgm_choice else None, music_style=edl.get("music"))
                master = adapter.export_platform(video_only, mix, vdir / "MASTER.mp4", profiles["youtube"])
            with job.step("FINAL_QA"):
                vision = None
                if router.has_real("vision"):     # 로컬 기술 점수만으로는 고품질 판정을 하지 않는다 (FAST 도 1회 평가)
                    shots_all = edl["shots"]
                    pick = sorted({round(i * (len(shots_all) - 1) / 7) for i in range(8)}) if len(shots_all) > 8 else list(range(len(shots_all)))
                    tts_of = {sc.scene_id: sc.tts_line for sc in plan.scenes}
                    frames, finfo = [], []
                    for j, i in enumerate(pick):
                        sh = shots_all[i]
                        fp = vdir / f"qa_{j}.jpg"
                        renderer.frame(sh, sh.duration / 2, i).resize((540, 960)).save(fp, quality=85)
                        frames.append(str(fp))
                        finfo.append({"caption": " ".join(w.text for w in sh.caption_words), "tts": tts_of.get(sh.scene_id, "")})
                    vision = vision_review(router, frames, f"제품: {p.name}. 원본 사진과 제품이 같은지, 상업 영상 품질인지 평가", finfo)
                qa = final_qa(master, plan, edl, bool(voice), caption_font_path() is not None, identity, vision,
                              caption_scale=getattr(renderer.captions, "last_scale", 1.0), photo_quality=result.get("photo_quality"))
                db.add_qa(job_id, "final", f"v{version}", qa["scores"], qa["passed"], json.dumps(qa["notes"], ensure_ascii=False))
                history.append({"version": version, "scores": qa["scores"], "failed": qa["failed"], "notes": qa["notes"]})
            if qa["passed"] or version > max_final or qa["verdict"] == "NEEDS_REVIEW":
                break
            actions = _repair(plan, qa, identity)
            history[-1]["repair"] = actions
            job.say(f"QA 미달 {qa['failed']} -> 수정: {actions}")
            if not actions:
                break
            for sc in plan.scenes:   # 수정된 장면은 take 파라미터도 갱신
                t = takes.get(sc.scene_id, {})
                if t.get("shot") != sc.shot or t.get("source") != sc.reference_image:
                    takes[sc.scene_id] = {**t, "shot": sc.shot, "source": sc.reference_image}
        result["qa"] = qa
        result["qa_history"] = history
        result["edl"] = edl_summary(edl)
        result["master"] = str(master)
        result["storyboard_sheet"] = str(contact_sheet(renderer, edl["shots"], vdir / "storyboard.jpg"))
        if video_paths and not (result.get("clips") or {}).get("used"):
            result.setdefault("warnings", []).append("올린 영상이 컷에 쓰이지 않았어요 (사용할 수 없는 클립이거나 구간이 짧음)")

        # 8 PLATFORM COPY + COMPLIANCE + EXPORT --------------------------------
        with job.step("COMPLIANCE"):
            copies, copy_report = adapter.platform_copy(plan, p, router, result.get("vision"), with_report=True)
            result.setdefault("grounding", {})["copy"] = copy_report
            texts = {f"{s.scene_id}.caption": s.caption.replace("[[", "").replace("]]", "") for s in plan.scenes}
            texts.update({f"{s.scene_id}.tts": s.tts_line for s in plan.scenes})
            assets = db.query("SELECT path, rights FROM assets WHERE job_id=?", (job_id,))
            gate = compliance.compliance_gate(p, texts, {k: copies[k] for k in platforms}, bool(label), assets)
            result["compliance"] = gate
            result["copies"] = copies
        exports = {}
        for pf in platforms:
            verdict = gate["platforms"][pf]["verdict"]
            if verdict not in ("PASS", "PASS_WITH_WARNING"):
                exports[pf] = {"file": None, "verdict": verdict, "reasons": gate["platforms"][pf]["reasons"]}
                continue
            prof = profiles[pf]
            cta_shots = []
            for s in cta:
                s2 = type(s)(**{**asdict(s), "caption_words": []})
                s2.caption_words = time_words(prof["cta_text"].replace("링크", "[[링크]]", 1), 0.08, min(1.2, s.duration * 0.5))
                cta_shots.append(s2)
            pf_cta = renderer.render(cta_shots, vdir / f"cta_{pf}.mp4")
            pf_video = adapter.concat([body_mp4, pf_cta], vdir / f"{pf}_video.mp4")
            out = adapter.export_platform(pf_video, mix, out_dir / f"{pf}.mp4", prof,
                                          max_duration=prof["max_duration"])
            exports[pf] = {"file": str(out), "verdict": verdict, "reasons": gate["platforms"][pf]["reasons"]}
        result["exports"] = exports
        renderer.close_clips()
        result["status"] = qa["verdict"]      # COMPLETE | QUALITY_FAIL | NEEDS_REVIEW (Vision 평가 없음)
        result["cost"] = db.job_cost(job_id)
        result["router_trace"] = router.trace
        result["log"] = job.log
        db.update_job(job_id, result["status"], result)
    except StrategyBlocked as e:
        result["status"] = "STRATEGY_BLOCKED"
        result["blocked"] = {"reason": "Conversion Audit 의 Quality Gate 를 통과하지 못해 영상 제작을 시작하지 않았어요", "gate": e.gate}
        result["log"] = job.log
        db.update_job(job_id, "STRATEGY_BLOCKED", result)
    except Exception as e:
        try:
            renderer.close_clips()
        except Exception:
            pass
        result["status"] = "FAILED"
        result["error"] = str(e)
        result["trace"] = traceback.format_exc()[-1500:]
        result["log"] = job.log
        db.update_job(job_id, "FAILED", result)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result
