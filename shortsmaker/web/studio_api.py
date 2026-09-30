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

PLATFORMS = ("youtube", "instagram", "tiktok", "threads")
MAX_PHOTOS = 12
MAX_PHOTO_BYTES = 30 * 1024 * 1024


class V2PublishRequest(BaseModel):
    platforms: list[str]
    privacy: str = "public"


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
        url: str = Form(""), name: str = Form(""), description: str = Form(""), features: str = Form(""),
        problem: str = Form(""), target: str = Form(""), price: str = Form(""), category: str = Form(""),
        affiliate: str = Form("NONE"), photo_rights: str = Form("OWNED"), reference_url: str = Form(""),
        mode: str = Form("PRO"), platforms: str = Form("youtube,instagram,tiktok,threads"),
        boxes: str = Form(""), feature_photos: str = Form(""),
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
        if not saved and not url.strip():
            raise HTTPException(400, "상품 URL 또는 상품 사진이 필요합니다.")
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
                  "problem": problem.strip(), "target": target.strip(), "price": price.strip(), "url": url.strip(),
                  "photos": saved, "photo_rights": photo_rights, "reference_url": reference_url.strip(),
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
            for pf, e in (r.get("exports") or {}).items():
                e["url"] = to_url(e.get("file"))
            for k in ("trace", "router_trace", "identity", "edl"):
                r.pop(k, None)
            out["result"] = r
        return out

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
