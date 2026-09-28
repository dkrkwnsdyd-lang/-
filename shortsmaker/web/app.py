"""웹 화면. / = SHOP SHORTS V2 스튜디오, /classic = 기존 사진 슬라이드 메이커, /control = API Control Center."""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..platforms import PLATFORM_LABELS, PUBLISHERS, PostMeta, publish_all
from ..sources import IMAGE_EXTS, resolve_inputs
from ..video import VideoOptions, make_video

STATIC = Path(__file__).parent / "static"


class PublishRequest(BaseModel):
    name: str
    title: str
    description: str = ""
    tags: str = ""
    privacy: str = "public"
    platforms: list[str]


def platform_status(cfg: dict) -> list[dict]:
    public_base = (cfg.get("general") or {}).get("public_base_url")
    out = []
    for name in PUBLISHERS:
        c = cfg.get(name) or {}
        if name == "youtube":
            ok = Path(c.get("token_file", "youtube_token.json")).exists() or \
                Path(c.get("client_secrets_file", "client_secret.json")).exists()
            hint = "client_secret.json 준비 후 'python -m shortsmaker youtube-auth' 실행"
        elif name == "instagram":
            ok = bool(c.get("access_token") and c.get("user_id"))
            hint = "config.yaml 에 instagram.access_token / user_id 입력"
        elif name == "threads":
            ok = bool(c.get("access_token") and c.get("user_id") and (public_base or c.get("video_url")))
            hint = "threads.access_token / user_id 와 general.public_base_url 필요"
        else:
            ok = bool(c.get("access_token"))
            hint = "config.yaml 에 tiktok.access_token 입력"
        out.append({"id": name, "label": PLATFORM_LABELS[name], "ready": ok, "hint": "" if ok else hint})
    return out


def create_app(cfg: dict | None = None, output_dir: str | Path = "output",
               upload_dir: str | Path = "uploads") -> FastAPI:
    cfg = cfg or {}
    output_dir, upload_dir = Path(output_dir), Path(upload_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Shorts Maker")
    app.mount("/outputs", StaticFiles(directory=output_dir), name="outputs")

    @app.get("/")
    def studio_page():
        return FileResponse(STATIC / "studio.html")

    @app.get("/classic")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/control")
    def control_page():
        return FileResponse(STATIC / "control.html")

    from .studio_api import register_studio
    register_studio(app, cfg, output_dir, upload_dir)

    @app.get("/api/platforms")
    def platforms():
        return platform_status(cfg)

    @app.post("/api/render")
    def render(
        files: list[UploadFile] = File(default=[]),
        urls: str = Form(""),
        order: str = Form(""),
        title: str = Form(""),
        captions: str = Form(""),
        seconds: float = Form(3.0),
        transition: float = Form(0.5),
        fit: str = Form("blur"),
        ken_burns: bool = Form(True),
        bgm: UploadFile | None = File(default=None),
    ):
        job = upload_dir / uuid.uuid4().hex[:12]
        job.mkdir(parents=True)
        saved: list[str] = []
        for i, f in enumerate(files):
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in IMAGE_EXTS:
                raise HTTPException(400, f"지원하지 않는 파일 형식: {f.filename}")
            dest = job / f"{i:03d}{suffix}"
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            saved.append(str(dest))
        url_list = [u.strip() for u in urls.splitlines() if u.strip()]
        # order: "f,u,f" 처럼 파일(f)/URL(u) 순서. 없으면 파일 먼저.
        kinds = [k for k in order.split(",") if k in ("f", "u")]
        if kinds.count("f") != len(saved) or kinds.count("u") != len(url_list):
            kinds = ["f"] * len(saved) + ["u"] * len(url_list)
        fi, ui = iter(saved), iter(url_list)
        inputs = [next(fi) if k == "f" else next(ui) for k in kinds]
        if not inputs:
            raise HTTPException(400, "사진을 올리거나 이미지/유튜브 URL 을 입력하세요.")

        opts = VideoOptions.from_dict(cfg.get("video"))
        opts.title = title.strip() or None
        opts.captions = [c.strip() for c in captions.splitlines()]
        opts.seconds_per_image = max(0.5, min(seconds, 15))
        opts.transition = max(0.0, min(transition, 2))
        opts.fit = fit if fit in ("blur", "crop") else "blur"
        opts.ken_burns = ken_burns
        if bgm is not None and bgm.filename:
            bgm_path = job / ("bgm" + Path(bgm.filename).suffix.lower())
            with open(bgm_path, "wb") as out:
                shutil.copyfileobj(bgm.file, out)
            opts.bgm_path = str(bgm_path)

        try:
            images = resolve_inputs(inputs, workdir=job / "src")
            name = f"short_{datetime.now():%Y%m%d_%H%M%S}_{job.name[:4]}.mp4"
            make_video(images, output_dir / name, opts)
        except Exception as e:
            raise HTTPException(400, str(e))
        return {"name": name, "url": f"/outputs/{name}"}

    @app.post("/api/publish")
    def publish(req: PublishRequest):
        if not re.fullmatch(r"[\w.-]+\.mp4", req.name) or not (output_dir / req.name).exists():
            raise HTTPException(404, "영상을 찾을 수 없습니다.")
        if not req.title.strip():
            raise HTTPException(400, "제목을 입력하세요.")
        meta = PostMeta(req.title.strip(), req.description.strip(),
                        [t.strip() for t in req.tags.split(",") if t.strip()], req.privacy)
        results = publish_all(output_dir / req.name, meta, req.platforms, cfg)
        return [r.__dict__ | {"label": PLATFORM_LABELS.get(r.platform, r.platform)} for r in results]

    return app
