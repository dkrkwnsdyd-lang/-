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


def run_job(inputs: dict, mode: str = "PRO", platforms: list[str] | None = None, out_root: str | Path = "output/v2",
            db: DB | None = None, router: Router | None = None, progress_cb=None, job_id: str | None = None,
            render: tuple[int, int, int] = (1080, 1920, 30)) -> dict:
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
            analyses = [analyze_photo(ph) for ph in photos]
            saved_by_name = {Path(orig).name: saved for orig, saved in zip(p.photos, photos)}
            p.feature_photos = {feat: saved_by_name[name] for feat, name in p.feature_photos.items()
                                if name in saved_by_name and feat in p.features}
            for orig, a in zip(p.photos, analyses):
                box = p.product_boxes.get(Path(orig).name)
                if box and len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1:
                    a.product_box = tuple(box)
                    a.focus = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
                    a.box_source = "user"
            # Vision LLM: 사용자가 지정하지 않은 제품 위치/특징-사진 연결을 자동으로 채운다 (실패해도 계속)
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
                    result.setdefault("warnings", []).append(
                        "사진에 개인 정보로 보이는 요소: " + ", ".join(privacy) + " - 제품 영역만 사용하도록 확인 후 게시")
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
        with job.step("SCRIPT"):
            data = llm_director(router, p, identity, mode) if router.has_real("llm") else rule_director(p, mode)
            if "_director" not in data:
                data["_director"] = "local:rule_director_v1"
            plan = direct_scenes(data, identity, p, mode)
            result["plan"] = plan.to_dict()

        renderer = MotionRenderer(width=render[0], height=render[1], fps=render[2])
        renderer.cache.boxes = {ph["path"]: tuple(ph["product_box"]) for ph in identity.photos if ph.get("focus")}
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

        # 6 TTS -----------------------------------------------------------------
        voice = {}
        if router.has_real("tts"):
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
            with job.step("EDIT"):
                edl = edit(plan, takes, voice, label=label,
                           zoomable_paths={ph['path'] for ph in identity.photos if zoomable(identity, ph['path'])})
            with job.step("RENDER"):
                body = [s for s in edl["shots"] if s.scene_id != plan.scenes[-1].scene_id]
                cta = [s for s in edl["shots"] if s.scene_id == plan.scenes[-1].scene_id]
                vdir = out_dir / f"v{version}"
                vdir.mkdir(exist_ok=True)
                body_mp4 = renderer.render(body, vdir / "body.mp4",
                                           progress_cb=lambda f: job.progress_cb and job.progress_cb(f"렌더 {f:.0%}"))
                cta_mp4 = renderer.render(cta, vdir / "cta_master.mp4")
                video_only = adapter.concat([body_mp4, cta_mp4], vdir / "master_video.mp4")
                mix = build_mix(edl["total"], edl["events"], edl["voice"], vdir / "mix.wav",
                                bgm_path=inputs.get("bgm_path"))
                master = adapter.export_platform(video_only, mix, vdir / "MASTER.mp4", profiles["youtube"])
            with job.step("FINAL_QA"):
                vision = None
                if mode == "PRO" and router.has_real("vision"):
                    frames = []
                    for i, s in enumerate(edl["shots"][:6]):
                        fp = vdir / f"qa_{i}.jpg"
                        renderer.frame(s, s.duration / 2, i).resize((540, 960)).save(fp, quality=85)
                        frames.append(str(fp))
                    vision = vision_review(router, frames, f"제품: {p.name}. 원본 사진과 제품이 같은지, 상업 영상 품질인지 평가")
                qa = final_qa(master, plan, edl, bool(voice), caption_font_path() is not None, identity, vision,
                              caption_scale=getattr(renderer.captions, "last_scale", 1.0))
                db.add_qa(job_id, "final", f"v{version}", qa["scores"], qa["passed"], json.dumps(qa["notes"], ensure_ascii=False))
                history.append({"version": version, "scores": qa["scores"], "failed": qa["failed"], "notes": qa["notes"]})
            if qa["passed"] or version > max_final:
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

        # 8 PLATFORM COPY + COMPLIANCE + EXPORT --------------------------------
        with job.step("COMPLIANCE"):
            copies = adapter.platform_copy(plan, p, router)
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
        result["status"] = "COMPLETE" if qa["passed"] else "QUALITY_FAIL"
        result["cost"] = db.job_cost(job_id)
        result["router_trace"] = router.trace
        result["log"] = job.log
        db.update_job(job_id, result["status"], result)
    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        result["trace"] = traceback.format_exc()[-1500:]
        result["log"] = job.log
        db.update_job(job_id, "FAILED", result)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result
