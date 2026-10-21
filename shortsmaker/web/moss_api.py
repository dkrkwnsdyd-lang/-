"""Web endpoints for optional MOSS-Image background and thumbnail creation."""
from __future__ import annotations

import io
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from ..studio.moss_image import (
    make_plan, generate_background, compose_cover, MAX_BYTES,
)

STATIC = Path(__file__).parent / "static"


class MossPlanRequest(BaseModel):
    scene: str = ""
    style: str = "lifestyle"
    model: str = "moss-image-sft-1.0"
    size: str = "720x1280"
    headline: str = ""
    product_name: str = ""


def register_moss(app: FastAPI, output_dir: str | Path) -> None:
    root = Path(output_dir) / "moss"

    @app.get("/moss")
    def moss_page():
        return FileResponse(STATIC / "moss.html")

    @app.post("/api/moss/plan")
    def moss_plan(req: MossPlanRequest):
        try:
            return make_plan(req.scene, style=req.style, model=req.model, size=req.size,
                             headline=req.headline, product_name=req.product_name)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/moss/generate")
    def moss_generate(
        scene: str = Form(""),
        style: str = Form("lifestyle"),
        headline: str = Form(""),
        product_name: str = Form(""),
        model: str = Form("moss-image-sft-1.0"),
        size: str = Form("720x1280"),
        approve_paid: bool = Form(False),
        product_photo: UploadFile | None = File(default=None),
    ):
        # Check approval before touching the paid API, saving media or even
        # creating a job directory. Never take a checkbox's absence as consent.
        if not approve_paid:
            raise HTTPException(403, "과금 가능성을 확인하고 이미지 생성에 명시적으로 동의해야 합니다.")
        if not os.environ.get("MOSS_API_KEY"):
            raise HTTPException(503, "MOSS_API_KEY 미설정: 유료 이미지 생성 요청을 시작하지 않았습니다.")
        try:
            plan = make_plan(scene, style=style, model=model, size=size,
                             headline=headline, product_name=product_name)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        photo_bytes = None
        if product_photo and product_photo.filename:
            if Path(product_photo.filename).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                raise HTTPException(400, "상품 사진은 jpg/png/webp만 사용할 수 있습니다.")
            photo_bytes = product_photo.file.read(MAX_BYTES + 1)
            if len(photo_bytes) > MAX_BYTES:
                raise HTTPException(413, "상품 사진은 20MB 이하여야 합니다.")
            try:
                with Image.open(io.BytesIO(photo_bytes)) as src:
                    src.verify()
            except (UnidentifiedImageError, OSError, ValueError):
                raise HTTPException(400, "유효한 이미지 파일이 아닙니다.")

        job_id = uuid.uuid4().hex[:12]
        job_dir = root / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / "moss-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        photo_path = None
        if photo_bytes is not None:
            photo_path = job_dir / ("original-product" + Path(product_photo.filename).suffix.lower())
            # Original bytes preserved; never provide them to MOSS text-to-image.
            photo_path.write_bytes(photo_bytes)
        try:
            report = generate_background(plan, job_dir / "background.png", approve_paid=approve_paid)
            cover_path = compose_cover(report["file"], photo_path,
                                       plan["headline"] or plan["product_name"], job_dir / "cover.png")
            result = {"job_id": job_id, "model": plan["model"], "usage": report["usage"],
                      "background": f"/outputs/moss/{job_id}/background.png",
                      "cover": f"/outputs/moss/{job_id}/cover.png",
                      "qa": "NEEDS_REVIEW", "publishable": False}
            (job_dir / "moss-result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        except (RuntimeError, ValueError, OSError, KeyError) as exc:
            # Do not echo providers' detailed response bodies or credentials.
            raise HTTPException(502, str(exc))
