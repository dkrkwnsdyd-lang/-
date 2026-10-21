"""SHOP SHORTS AI 편집팀 V0.3: 기존 FastAPI/PWA 안에서 실행되는 20초 5장면 편집.

기존 영상 파이프라인을 교체하지 않고, photo-only 편집 기능을 별도 API로 추가한다.
비밀키/외부 API/자동 게시 기능은 호출하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from ..video import VideoOptions, ffmpeg_exe, make_video

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_AUDIO_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 32_000_000
AUDIO_TYPES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shorts-edit-team")
_IO_LOCK = threading.RLock()


def captions_for(product: str, hook: str = "", problem: str = "",
                 solution: str = "", proof: str = "", cta: str = "") -> list[str]:
    """사실 미확인 후기/판매량/할인/효능을 자동으로 꾸며내지 않는다."""
    return [
        hook.strip() or "이 제품, 살까 말까?",
        problem.strip() or "고민되는 점을 확인해 보세요",
        solution.strip() or f"{product}의 특징을 살펴보세요",
        proof.strip() or "가격과 상세 사양은 판매 페이지에서 확인하세요",
        cta.strip() or "상세 정보는 설명란에서 확인하세요",
    ]


def _text(value: str, label: str, limit: int) -> str:
    value = value.strip()
    if len(value) > limit:
        raise HTTPException(422, f"{label}은 최대 {limit}자까지 입력할 수 있습니다.")
    return value


async def _picture(file: UploadFile, path: Path) -> None:
    raw = await file.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "사진은 각각 15MB 이하여야 합니다.")
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP"):
                raise HTTPException(415, "JPG, PNG, WEBP 사진만 지원합니다.")
            if im.width * im.height > MAX_PIXELS:
                raise HTTPException(413, "이미지 해상도가 너무 큽니다.")
            image = ImageOps.exif_transpose(im).convert("RGB")
            image.thumbnail((1800, 3000), Image.Resampling.LANCZOS)
            image.save(path, format="JPEG", quality=91, optimize=True)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise HTTPException(415, "읽을 수 없는 사진입니다.") from exc


async def _audio(file: UploadFile, folder: Path) -> Path:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_TYPES:
        raise HTTPException(415, "음성 파일 형식을 확인해 주세요.")
    raw = await file.read(MAX_AUDIO_BYTES + 1)
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "음성 파일은 30MB 이하여야 합니다.")
    path = folder / f"voice{ext}"
    path.write_bytes(raw)
    return path


def _state(folder: Path) -> dict:
    path = folder / "status.json"
    if not path.is_file():
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return json.loads(path.read_text(encoding="utf-8"))


def _set_state(folder: Path, **updates) -> dict:
    with _IO_LOCK:
        path = folder / "status.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        old.update(updates)
        temp = folder / "status.json.tmp"
        temp.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
        return old


def _mix_voice(video: Path, voice: Path) -> None:
    dest = video.with_name("voiced.mp4")
    command = [
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-i", str(video), "-i", str(voice),
        "-filter_complex", "[1:a]apad,atrim=0:20[a]",
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-t", "20", "-movflags", "+faststart", str(dest),
    ]
    p = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if p.returncode:
        dest.unlink(missing_ok=True)
        raise RuntimeError("음성 파일을 합치지 못했습니다. 형식과 길이를 확인하세요.")
    os.replace(dest, video)


def _render(folder: Path) -> None:
    try:
        job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        _set_state(folder, status="rendering", stage="20초 5장면 영상 렌더링 중", progress=20)
        preview = job["mode"] == "preview"
        opts = VideoOptions(
            width=360 if preview else 1080,
            height=640 if preview else 1920,
            fps=15 if preview else 30,
            seconds_per_image=4.0,
            transition=0.0,
            ken_burns=True,
            fit="blur",
            title=f'{job["product_name"]}\n{job["disclosure"]}',
            captions=job["captions"],
            max_duration=20.0,
            crf=24 if preview else 21,
            preset="veryfast",
        )
        photos = [folder / ("photo1.jpg" if i % 2 == 0 else "photo2.jpg") for i in range(5)]
        result = folder / "result.mp4"
        make_video(photos, result, opts)
        if job["voice"]:
            _set_state(folder, stage="음성 합성 중", progress=85)
            _mix_voice(result, folder / job["voice"])
        _set_state(folder, status="completed", stage="완료", progress=100,
                   download_url=f'/api/edit-team/jobs/{folder.name}/file')
    except Exception as exc:
        # 사용자가 오류 원인을 파악할 수 있도록 하되 traceback/키는 노출하지 않는다.
        _set_state(folder, status="failed", stage="실패", progress=0,
                   error=f"{type(exc).__name__}: {str(exc)[:300]}")


def register_edit_team(app: FastAPI, output_dir: Path) -> None:
    """기존 create_app 안에 호출해야 로그인/HTTPS 설정과 출력 경로를 공유한다."""
    jobs = Path(output_dir) / "edit-team"
    jobs.mkdir(parents=True, exist_ok=True)

    def locate(job_id: str) -> Path:
        if not ID_RE.fullmatch(job_id):
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        folder = jobs / job_id
        if not folder.is_dir():
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return folder

    @app.get("/api/edit-team/health")
    def health():
        return {"ok": True, "version": "0.3", "mode": "integrated", "max_image_mb": 15}

    @app.post("/api/edit-team/jobs", status_code=202)
    async def create_job(
        request: Request,
        photo1: UploadFile = File(...),
        photo2: UploadFile = File(...),
        product_name: str = Form("상품 소개"),
        mode: str = Form("preview"),
        disclosure: str = Form("이 콘텐츠는 제휴활동으로 수수료를 제공받을 수 있습니다."),
        hook: str = Form(""),
        problem: str = Form(""),
        solution: str = Form(""),
        proof: str = Form(""),
        cta: str = Form(""),
        voice: UploadFile | None = File(default=None),
    ):
        if mode not in ("preview", "final"):
            raise HTTPException(422, "preview 또는 final을 선택하세요.")
        # FastAPI Form 기본값 동작과 무관하게 의도적으로 비운 고지는 거절.
        values = await request.form()
        if "disclosure" in values and not str(values["disclosure"]).strip():
            raise HTTPException(422, "광고 고지를 입력하세요.")
        product = _text(product_name, "상품명", 45) or "상품 소개"
        notice = _text(disclosure, "광고 고지", 80)
        if not notice:
            raise HTTPException(422, "광고 고지를 입력하세요.")
        pieces = [
            _text(v, label, 120) for label, v in
            (("HOOK", hook), ("문제", problem), ("해결", solution),
             ("근거", proof), ("CTA", cta))
        ]
        job_id = uuid.uuid4().hex
        folder = jobs / job_id
        folder.mkdir(parents=True, exist_ok=False)
        try:
            await _picture(photo1, folder / "photo1.jpg")
            await _picture(photo2, folder / "photo2.jpg")
            audio_path = await _audio(voice, folder) if voice and voice.filename else None
            details = {
                "product_name": product, "disclosure": notice, "captions": captions_for(product, *pieces),
                "mode": mode, "voice": audio_path.name if audio_path else None,
            }
            (folder / "job.json").write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")
            state = _set_state(folder, id=job_id, mode=mode, status="queued",
                               stage="작업 대기 중", progress=5, download_url=None)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        _POOL.submit(_render, folder)
        return state

    @app.get("/api/edit-team/jobs/{job_id}")
    def get_job(job_id: str):
        return _state(locate(job_id))

    @app.get("/api/edit-team/jobs/{job_id}/file")
    def download(job_id: str):
        folder = locate(job_id)
        if _state(folder).get("status") != "completed" or not (folder / "result.mp4").is_file():
            raise HTTPException(404, "영상이 아직 준비되지 않았습니다.")
        return FileResponse(folder / "result.mp4", media_type="video/mp4",
                            filename=f"shop-shorts-{job_id[:8]}.mp4")
