"""사진 여러 장 -> 세로형(9:16) 숏폼 영상(mp4).

- 가로 사진(유튜브 캡처/썸네일 등)은 흐린 배경 위에 가운데 배치 (잘리지 않음)
- 켄번스(천천히 확대/이동) 효과 + 크로스페이드 전환
- 상단 제목 / 하단 자막
- 배경음악(없으면 무음 트랙)

결과물은 H.264 + AAC, 1080x1920, 30fps 로 유튜브 쇼츠, 인스타 릴스,
쓰레드, 틱톡 모두의 업로드 규격을 만족한다.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# 켄번스 여유 배율: 기본 캔버스를 출력보다 크게 만들어 두고 잘라내며 움직인다
_KB_MARGIN = 1.15

FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    # macOS
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/AppleGothic.ttf",
    # Linux
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@dataclass
class VideoOptions:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    seconds_per_image: float = 3.0
    transition: float = 0.5          # 크로스페이드 길이(초), 0 이면 컷 전환
    ken_burns: bool = True
    fit: str = "blur"                # "blur": 흐린 배경 + 전체 표시, "crop": 화면 꽉 채우기
    title: str | None = None         # 영상 내내 상단에 표시
    captions: list[str] = field(default_factory=list)  # 사진별 하단 자막
    font_path: str | None = None
    bgm_path: str | None = None
    bgm_volume: float = 0.8
    max_duration: float = 60.0       # 모든 플랫폼에서 안전한 길이
    crf: int = 20
    preset: str = "medium"

    @classmethod
    def from_dict(cls, data: dict | None) -> "VideoOptions":
        data = dict(data or {})
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def ffmpeg_exe() -> str:
    env = os.environ.get("FFMPEG_BINARY")
    if env:
        return env
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def find_font(preferred: str | None = None) -> str | None:
    for cand in [preferred, *FONT_CANDIDATES]:
        if cand and Path(cand).exists():
            return cand
    return None


def _load_font(path: str | None, size: int) -> ImageFont.ImageFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------- 이미지 준비

def compose_canvas(img: Image.Image, width: int, height: int, fit: str) -> Image.Image:
    """사진을 width x height 세로 캔버스에 배치."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if fit == "crop":
        return ImageOps.fit(img, (width, height), Image.LANCZOS)

    # 배경: 화면을 꽉 채우도록 확대 후 흐리게 + 어둡게
    bg = ImageOps.fit(img, (width // 4, height // 4), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=12)).resize((width, height), Image.BILINEAR)
    bg = Image.eval(bg, lambda v: int(v * 0.55))

    fg = ImageOps.contain(img, (width, height), Image.LANCZOS)
    bg.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
    return bg


def _wrap(text: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw, max_w: int) -> list[str]:
    """픽셀 폭 기준 줄바꿈 (띄어쓰기 우선, 필요하면 글자 단위)."""
    lines: list[str] = []
    for para in text.splitlines() or [""]:
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip() if cur else word
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            cur = ""
            for ch in word:
                if draw.textlength(cur + ch, font=font) > max_w and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
        lines.append(cur)
    return lines


def render_text_layer(width: int, height: int, title: str | None, caption: str | None,
                      font_path: str | None) -> Image.Image | None:
    """제목/자막을 그린 투명 레이어 (없으면 None)."""
    if not title and not caption:
        return None
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    margin = int(width * 0.07)
    max_w = width - margin * 2

    def block(text: str, size: int, y: int, anchor_bottom: bool, box: bool):
        font = _load_font(font_path, size)
        lines = _wrap(text, font, draw, max_w)[:4]
        line_h = int(size * 1.3)
        total_h = line_h * len(lines)
        top = y - total_h if anchor_bottom else y
        if box:
            widest = max(draw.textlength(l, font=font) for l in lines)
            pad = int(size * 0.45)
            draw.rounded_rectangle(
                [(width - widest) / 2 - pad, top - pad, (width + widest) / 2 + pad, top + total_h + pad * 0.6],
                radius=pad, fill=(0, 0, 0, 150))
        for i, line in enumerate(lines):
            draw.text((width / 2, top + i * line_h), line, font=font, anchor="ma",
                      fill=(255, 255, 255, 255), stroke_width=max(2, size // 14),
                      stroke_fill=(0, 0, 0, 255))

    if title:
        block(title, int(width * 0.075), int(height * 0.08), anchor_bottom=False, box=False)
    if caption:
        block(caption, int(width * 0.055), int(height * 0.84), anchor_bottom=True, box=True)
    return layer


# ---------------------------------------------------------------- 타임라인

def plan_timeline(n_images: int, opts: VideoOptions) -> tuple[float, float, float]:
    """(사진당 길이, 전환 길이, 전체 길이) - 최대 길이를 넘으면 사진당 길이를 줄인다."""
    d = opts.seconds_per_image
    t = min(opts.transition, d / 2) if n_images > 1 else 0.0
    total = n_images * d - (n_images - 1) * t
    if total > opts.max_duration:
        # n*d - (n-1)*t = max  (t 는 d 에 비례하도록 유지)
        ratio = t / d if d else 0
        d = opts.max_duration / (n_images - (n_images - 1) * ratio)
        t = d * ratio
        total = opts.max_duration
    return d, t, total


class _Clip:
    def __init__(self, canvas: Image.Image, overlay: Image.Image | None, index: int,
                 out_size: tuple[int, int], ken_burns: bool):
        self.canvas = canvas
        self.overlay = overlay
        self.out_size = out_size
        self.ken_burns = ken_burns
        # 사진마다 확대/축소, 이동 방향을 번갈아 준다
        self.zoom_in = index % 2 == 0
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        self.pan = dirs[index % 4]

    def frame(self, progress: float) -> Image.Image:
        cw, ch = self.canvas.size
        ow, oh = self.out_size
        if not self.ken_burns:
            img = self.canvas.resize(self.out_size, Image.BILINEAR) if (cw, ch) != (ow, oh) else self.canvas
        else:
            p = progress * progress * (3 - 2 * progress)  # smoothstep
            z0, z1 = (1.0, 1 / _KB_MARGIN * 1.02) if self.zoom_in else (1 / _KB_MARGIN * 1.02, 1.0)
            scale = z0 + (z1 - z0) * p            # 캔버스 대비 잘라낼 비율
            bw, bh = cw * scale, ch * scale
            free_x, free_y = cw - bw, ch - bh
            cx = free_x / 2 + self.pan[0] * free_x * 0.35 * (p - 0.5)
            cy = free_y / 2 + self.pan[1] * free_y * 0.35 * (p - 0.5)
            img = self.canvas.transform(self.out_size, Image.EXTENT,
                                        (cx, cy, cx + bw, cy + bh), Image.BILINEAR)
        if self.overlay is not None:
            img = img.copy()
            img.paste(self.overlay, (0, 0), self.overlay)
        return img


def make_video(images: list[str | Path], output: str | Path, opts: VideoOptions | None = None,
               progress_cb=None) -> Path:
    """사진 목록으로 숏폼 영상을 만들고 경로를 돌려준다."""
    opts = opts or VideoOptions()
    if not images:
        raise ValueError("사진이 필요합니다.")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    w, h, fps = opts.width, opts.height, opts.fps
    font_path = find_font(opts.font_path)

    d, t, total = plan_timeline(len(images), opts)
    kb = _KB_MARGIN if opts.ken_burns else 1.0
    cw, ch = int(w * kb), int(h * kb)

    clips: list[_Clip] = []
    for i, path in enumerate(images):
        with Image.open(path) as im:
            canvas = compose_canvas(im, cw, ch, opts.fit)
        caption = opts.captions[i] if i < len(opts.captions) else None
        overlay = render_text_layer(w, h, opts.title, caption, font_path)
        clips.append(_Clip(canvas, overlay, i, (w, h), opts.ken_burns))

    n_frames = max(1, round(total * fps))
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    if opts.bgm_path:
        fade = min(1.5, total / 3)
        cmd += ["-stream_loop", "-1", "-i", str(opts.bgm_path),
                "-af", f"volume={opts.bgm_volume},afade=t=out:st={total - fade:.3f}:d={fade:.3f}"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(fps),
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart", str(output)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    step = d - t
    try:
        for f in range(n_frames):
            now = f / fps
            i = min(int(now // step) if step > 0 else 0, len(clips) - 1)
            local = now - i * step
            frame = clips[i].frame(min(local / d, 1.0))
            # 이전 사진과 겹치는 구간이면 크로스페이드
            if t > 0 and i > 0 and local < t:
                prev = clips[i - 1].frame(min((local + step) / d, 1.0))
                frame = Image.blend(prev, frame, local / t)
            proc.stdin.write(frame.tobytes())
            if progress_cb and f % fps == 0:
                progress_cb(f / n_frames)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg 인코딩 실패:\n{err}")
    if progress_cb:
        progress_cb(1.0)
    return output
