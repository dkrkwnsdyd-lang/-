"""V2 스튜디오 API: 작업 생성(백그라운드), 상태/결과 조회, API Control Center, 플랫폼 게시."""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..db import DB
from ..platforms import PostMeta, publish_all
from ..providers import Router
from ..sources import IMAGE_EXTS
from ..studio.clips import VIDEO_EXTS

PLATFORMS = ("youtube", "instagram", "tiktok", "threads")
MAX_PHOTOS = 12
MAX_PHOTO_BYTES = 30 * 1024 * 1024
MAX_VIDEOS = 4
MAX_VIDEO_BYTES = 200 * 1024 * 1024


class V2PublishRequest(BaseModel):
    platforms: list[str]
    privacy: str = "public"



class RenderRequest(BaseModel):
    edits: dict = {}
    force: bool = False            # Quality Gate 미통과여도 사용자가 확인하고 제작
    generate_ai: bool = False      # True 일 때만 AI 영상 생성(비용 발생 가능). 캐시된 결과는 동의 없이 재사용


class StrategyRequest(BaseModel):
    action: str = "regenerate"     # regenerate | pick | revise
    stage: str = "audit"
    id: str | None = None
    style: str | None = None
    auto: bool | None = None

def _budget(v: str) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 0 < x <= 10000 else None


def register_studio(app: FastAPI, cfg: dict, output_dir: Path, upload_dir: Path) -> None:
    db = DB(Path(output_dir).resolve().parent / "data" / "shorts.db")
    live: dict[str, list[str]] = {}

    def to_url(path: str | None) -> str | None:
        if not path:
            return None
        try:
            return "/outputs/" + Path(path).resolve().relative_to(Path(output_dir).resolve()).as_posix()
        except ValueError:
            return None

    @app.post("/api/v2/jobs")
    def create_job(
        photos: list[UploadFile] = File(default=[]),
        videos: list[UploadFile] = File(default=[]),
        url: str = Form(""), name: str = Form(""), description: str = Form(""), features: str = Form(""),
        problem: str = Form(""), target: str = Form(""), price: str = Form(""), category: str = Form(""),
        affiliate: str = Form("NONE"), photo_rights: str = Form("OWNED"), reference_url: str = Form(""),
        mode: str = Form("PRO"), platforms: str = Form("youtube,instagram,tiktok,threads"),
        boxes: str = Form(""), feature_photos: str = Form(""), my_take: str = Form(""), compact: str = Form(""),
        preview: str = Form(""), video_style: str = Form("FAST_COMMERCE"), auto_strategy: str = Form("1"),
        actor_mode: str = Form("AUTO"), cost_mode: str = Form("BALANCED"), monthly_budget: str = Form(""),
    ):
        if len(photos) > MAX_PHOTOS:
            raise HTTPException(400, f"사진은 최대 {MAX_PHOTOS}장까지 올릴 수 있어요.")
        job_id = uuid.uuid4().hex[:10]
        up = Path(upload_dir) / f"v2_{job_id}"
        up.mkdir(parents=True, exist_ok=True)
        saved = []
        for i, f in enumerate(photos):
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in IMAGE_EXTS:
                raise HTTPException(400, f"지원하지 않는 파일 형식: {f.filename}")
            dst = up / f"{i:02d}{suffix}"
            with open(dst, "wb") as out:
                shutil.copyfileobj(f.file, out)
            if dst.stat().st_size > MAX_PHOTO_BYTES:
                shutil.rmtree(up, ignore_errors=True)
                raise HTTPException(400, f"사진 한 장은 {MAX_PHOTO_BYTES // 1024 // 1024}MB 이하여야 해요: {f.filename}")
            saved.append(str(dst))
        if len(videos) > MAX_VIDEOS:
            shutil.rmtree(up, ignore_errors=True)
            raise HTTPException(400, f"영상은 최대 {MAX_VIDEOS}개까지 올릴 수 있어요.")
        saved_videos = []
        for i, f in enumerate(videos):
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in VIDEO_EXTS:
                shutil.rmtree(up, ignore_errors=True)
                raise HTTPException(400, f"지원하지 않는 영상 형식: {f.filename}")
            dst = up / f"clip{i:02d}{suffix}"
            with open(dst, "wb") as out:
                shutil.copyfileobj(f.file, out)
            if dst.stat().st_size > MAX_VIDEO_BYTES:
                shutil.rmtree(up, ignore_errors=True)
                raise HTTPException(400, f"영상 하나는 {MAX_VIDEO_BYTES // 1024 // 1024}MB 이하여야 해요: {f.filename}")
            saved_videos.append(str(dst))
        if not saved and not url.strip():
            shutil.rmtree(up, ignore_errors=True)
            raise HTTPException(400, "상품 사진이 필요합니다. 영상은 사진과 함께 올려주세요." if saved_videos
                                else "상품 URL 또는 상품 사진이 필요합니다.")
        # boxes: {"사진 순번": [x0,y0,x1,y1]} (0~1) -> 저장된 파일명 기준으로 변환
        product_boxes: dict[str, list[float]] = {}
        try:
            raw = json.loads(boxes) if boxes.strip() else {}
        except ValueError:
            raise HTTPException(400, "제품 영역(boxes) 형식이 올바르지 않습니다.")
        for idx, box in raw.items():
            try:
                i, b = int(idx), [float(v) for v in box]
            except (ValueError, TypeError):
                raise HTTPException(400, "제품 영역(boxes) 형식이 올바르지 않습니다.")
            if 0 <= i < len(saved) and len(b) == 4 and 0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1:
                product_boxes[Path(saved[i]).name] = b
        # feature_photos: {"특징 문장": 사진 순번} -> 저장된 파일명 기준으로 변환
        linked: dict[str, str] = {}
        try:
            fp_raw = json.loads(feature_photos) if feature_photos.strip() else {}
            for feat, idx in fp_raw.items():
                i = int(idx)
                if 0 <= i < len(saved):
                    linked[str(feat)] = Path(saved[i]).name
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(400, "특징-사진 연결(feature_photos) 형식이 올바르지 않습니다.")
        mode = mode.upper() if mode.upper() in ("FAST", "PRO") else "PRO"
        pfs = [p for p in platforms.split(",") if p in PLATFORMS] or list(PLATFORMS)
        inputs = {"name": name.strip(), "description": description.strip(), "features": features,
                  "problem": problem.strip(), "target": target.strip(), "my_take": my_take.strip()[:200], "compact": compact == "1", "preview": preview == "1",
                  "video_style": video_style if video_style in ("FAST_COMMERCE", "STORY_AD", "UGC_REVIEW") else "FAST_COMMERCE",
                  "strategy_auto": auto_strategy != "0",
                  "actor_mode": actor_mode if actor_mode in ("PRODUCT_ONLY", "REAL_UGC", "AI_PRESENTER", "AI_PRODUCT_UGC", "AUTO") else "AUTO",
                  "cost_mode": cost_mode if cost_mode in ("ECONOMY", "BALANCED", "PREMIUM") else "BALANCED",
                  "monthly_budget": _budget(monthly_budget), "price": price.strip(), "url": url.strip(),
                  "photos": saved, "videos": saved_videos, "photo_rights": photo_rights, "reference_url": reference_url.strip(),
                  "affiliate": affiliate, "category_hint": category, "product_boxes": product_boxes,
                  "feature_photos": linked}
        live[job_id] = []

        def work():
            from ..studio.pipeline import run_job
            router = Router(db=db, job_id=job_id)
            run_job(inputs, mode, pfs, out_root=Path(output_dir) / "v2", db=db, router=router,
                    progress_cb=lambda m: live[job_id].append(m), job_id=job_id)

        threading.Thread(target=work, daemon=True).start()
        return {"job_id": job_id}

    @app.get("/api/v2/jobs/{job_id}")
    def job_status(job_id: str):
        job = db.job(job_id)
        if not job:
            if job_id in live:
                return {"job_id": job_id, "status": "PENDING", "steps": [], "log": live[job_id][-8:]}
            raise HTTPException(404, "작업 없음")
        out = {"job_id": job_id, "status": job["status"], "mode": job["mode"], "steps": db.steps(job_id),
               "log": live.get(job_id, [])[-8:], "cost": db.job_cost(job_id)}
        if job["result_json"] and job["status"] not in ("RUNNING", "PENDING"):
            r = json.loads(job["result_json"])
            r["master_url"] = to_url(r.get("master"))
            r["storyboard_url"] = to_url(r.get("storyboard_sheet"))
            pv = r.get("preview")
            if pv:                          # Preview: 장면 카드 이미지 주소 (서버 경로는 내보내지 않는다)
                pv["thumb_urls"] = {k: to_url(v) for k, v in pv.pop("thumbs", {}).items()}
                pv["photos"] = [{"index": x["index"], "url": to_url(x["file"])} for x in pv.get("photos", [])]
            r.pop("director_data", None)
            if r.get("strategy"):
                r["strategy"] = {k: v for k, v in r["strategy"].items() if k not in ("draft_script",)}
            for pf, e in (r.get("exports") or {}).items():
                e["url"] = to_url(e.get("file"))
            for k in ("trace", "router_trace", "identity", "edl"):
                r.pop(k, None)
            out["result"] = r
        return out

    def _spawn_from(job_id: str, req_edits: dict | None, preview: bool, force: bool = False, generate_ai: bool = False) -> dict:
        """미리보기 작업에서 확정한 대본/전략으로 새 작업을 만든다 (원래 작업은 보존). preview=True 면 Storyboard 만, False 면 MP4 까지."""
        job = db.job(job_id)
        if not job or job["status"] not in ("PREVIEW_READY", "STRATEGY_BLOCKED"):
            raise HTTPException(400, "미리보기가 준비된 작업이 아니에요")
        base = json.loads(job["input_json"] or "{}")
        res = json.loads(job["result_json"] or "{}")
        if not res.get("director_data"):
            raise HTTPException(400, "미리보기 대본 정보를 찾을 수 없어요")
        state = res.get("strategy")
        if not preview and state and not (state.get("gate") or {}).get("passed", True) and not force:
            fails = "; ".join(f"{f['code']}({f['detail']})" for f in state["gate"]["failures"])
            raise HTTPException(409, f"Quality Gate 미통과: {fails}. 수정하거나 '그래도 제작'을 선택하세요.")
        new_id = uuid.uuid4().hex[:10]
        inputs = {**base, "preview": preview, "director_data": res["director_data"], "strategy_state": state,
                  "edits": req_edits or None, "strategy_force": force, "generate_ai": bool(generate_ai), "video_style": (state or {}).get("style", base.get("video_style", "FAST_COMMERCE"))}
        live[new_id] = []

        def work():
            from ..studio.pipeline import run_job
            router = Router(db=db, job_id=new_id)
            run_job(inputs, job["mode"], None, out_root=Path(output_dir) / "v2", db=db, router=router,
                    progress_cb=lambda m: live[new_id].append(m), job_id=new_id)

        threading.Thread(target=work, daemon=True).start()
        return {"job_id": new_id, "from_preview": job_id}

    @app.post("/api/v2/jobs/{job_id}/render")
    def render_from_preview(job_id: str, req: RenderRequest):
        """[영상 제작]: 미리보기에서 확인/수정한 스토리보드로만 MP4 를 만든다."""
        return _spawn_from(job_id, req.edits, preview=False, force=req.force, generate_ai=req.generate_ai)

    @app.post("/api/v2/jobs/{job_id}/storyboard")
    def storyboard_from_strategy(job_id: str, req: RenderRequest):
        """[Storyboard 만들기]: (전략을 고치고 난 뒤) 확정한 대본으로 Storyboard/미리보기를 다시 만든다. MP4 는 만들지 않는다."""
        return _spawn_from(job_id, req.edits, preview=True)

    @app.post("/api/v2/jobs/{job_id}/ai-scenes")
    def generate_ai_scenes(job_id: str, req: RenderRequest):
        """[AI 장면 생성]: 사용자가 비용을 확인하고 눌렀을 때만 AI 영상 API 를 호출해 미리보기를 다시 만든다 (MP4 최종 렌더는 하지 않음).
        장면 하나만 다시 만들려면 edits.scenes.<id>.ai = {action: regenerate|revert, prompt, provider}. 같은 입력은 캐시를 재사용해 API 를 다시 부르지 않는다."""
        return _spawn_from(job_id, req.edits, preview=True, generate_ai=True)

    @app.post("/api/v2/jobs/{job_id}/strategy")
    def strategy_action(job_id: str, req: StrategyRequest):
        """단계별 [재생성] / 후보 선택 / 자동 수정. 앞 단계 결과는 재사용하고 선택한 단계부터 다시 계산한다 (몇십 초 걸릴 수 있음)."""
        from ..studio import strategy as sm
        from ..studio.product import ProductInput
        job = db.job(job_id)
        if not job or job["status"] not in ("PREVIEW_READY", "STRATEGY_BLOCKED"):
            raise HTTPException(400, "전략을 고칠 수 있는 작업이 아니에요")
        res = json.loads(job["result_json"] or "{}")
        state = res.get("strategy")
        if not state:
            raise HTTPException(400, "전략 결과가 없는 작업이에요")
        p = ProductInput.from_dict(json.loads(job["input_json"] or "{}"))
        style = req.style if req.style in sm.STYLES else state["style"]
        ident = type("I", (), {"color_reference": (res.get("identity") or {}).get("color_reference", []), "photos": []})()
        ctx = sm.make_ctx(p, style, job["mode"], ident, res.get("vision"), reference=res.get("reference"), has_clip=bool(p.videos))
        ctx.n_photos = len(p.photos)
        router = Router(db=db, job_id=job_id)
        try:
            if req.action == "pick":
                start = sm.pick(state, req.stage, req.id or "")
            elif req.action == "revise":
                start = "audit"
            elif req.stage in sm.STAGES:
                start = req.stage
            else:
                raise ValueError("알 수 없는 단계예요")
            if style != state["style"]:
                start = "hook"
            new = sm.run_strategy(router, ctx, state, start=start, auto=state["auto"] if req.auto is None else req.auto)
        except ValueError as e:
            raise HTTPException(400, str(e))
        res["strategy"] = new
        res["director_data"] = sm.to_director_data(ctx, new)
        res["storyboard_stale"] = True               # 장면 카드는 이전 대본 기준 -> [Storyboard 만들기] 필요
        db.update_job(job_id, job["status"], res)
        sm.save_state(Path(output_dir) / "v2" / job_id, new)
        return {"strategy": new, "storyboard_stale": True}

    @app.get("/api/v2/jobs")
    def jobs():
        return db.query("SELECT id, mode, status, product_name, total_cost, created_at FROM jobs ORDER BY created_at DESC LIMIT 30")

    @app.post("/api/v2/jobs/{job_id}/publish")
    def publish(job_id: str, req: V2PublishRequest):
        job = db.job(job_id)
        if not job or not job["result_json"]:
            raise HTTPException(404, "작업 없음")
        r = json.loads(job["result_json"])
        results = []
        for pf in req.platforms:
            e = (r.get("exports") or {}).get(pf) or {}
            if not e.get("file"):
                results.append({"platform": pf, "ok": False, "error": f"게시 불가: {e.get('verdict', '파일 없음')}"})
                continue
            c = r["copies"][pf]
            if pf == "youtube":
                meta = PostMeta(c["title"], c["description"], [], req.privacy)
            else:
                meta = PostMeta(c.get("caption") or c.get("post") or "", "", [], req.privacy)
            res = publish_all(e["file"], meta, [pf], cfg)[0]
            results.append(res.__dict__)
        return results

    @app.get("/api/v2/control-center")
    def control_center(test: bool = False):
        return Router(db=db).control_center(test=test)

    @app.post("/api/v2/control-center/test")
    def control_test(provider: str | None = None):
        rows = Router(db=db).control_center(test=True)
        return [r for r in rows if provider in (None, r["provider"])]

    @app.post("/api/v2/control-center/test-fallback")
    def test_fallback():
        """유료 호출 없이 폴백 체인 검증: 실제 provider 를 강제로 실패시키고 local 로 떨어지는지 확인."""
        from ..providers.base import Provider, ProviderError

        class Failing(Provider):
            name = "failing"

            def configured(self):
                return True

            def json(self, model, **kw):
                raise ProviderError("simulated failure")

        from ..providers import ModelEntry
        reg = [ModelEntry("failing", "llm", "sim", 1, True, 0, 0, ["json"]),
               ModelEntry("local", "llm", "rule_director_v1", 9, True, 0, 2, ["json"])]
        router = Router(providers={"failing": Failing()}, registry=reg, status_file=Path(output_dir) / ".fallback_test.json",
                        sleep=lambda s: None)
        res = router.run("llm", "json", local_fn=lambda: {"ok": True}, system="", user="")
        return {"final_provider": res.provider, "trace": router.trace, "ok": res.provider == "local"}
