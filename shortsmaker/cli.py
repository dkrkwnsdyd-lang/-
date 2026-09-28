"""명령줄 사용법.

  python -m shortsmaker make 사진1.jpg 사진2.jpg --title "제목" -o output/short.mp4
  python -m shortsmaker publish output/short.mp4 --title "제목" --platforms youtube,instagram
  python -m shortsmaker auto 사진폴더/ --title "제목" --platforms all
  python -m shortsmaker youtube-auth
  python -m shortsmaker web
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .config import load_config
from .platforms import PLATFORM_LABELS, PUBLISHERS, PostMeta, publish_all
from .sources import resolve_inputs
from .video import VideoOptions, make_video


def _split(text: str | None, sep: str) -> list[str]:
    return [s.strip() for s in text.split(sep)] if text else []


def _platforms(text: str) -> list[str]:
    if text.strip() == "all":
        return list(PUBLISHERS)
    return _split(text, ",")


def _add_video_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("inputs", nargs="+", help="사진 파일/폴더/이미지 URL/유튜브 영상 URL")
    p.add_argument("-o", "--output", help="출력 mp4 경로 (기본: output/short_날짜.mp4)")
    p.add_argument("--title", help="영상 상단 제목 (게시 제목으로도 사용)")
    p.add_argument("--captions", help="사진별 자막, '|' 로 구분. 예: '첫장|둘째장'")
    p.add_argument("--seconds", type=float, help="사진 한 장당 초 (기본 3)")
    p.add_argument("--transition", type=float, help="전환 효과 초 (기본 0.5)")
    p.add_argument("--fit", choices=["blur", "crop"], help="blur: 흐린 배경, crop: 꽉 채우기")
    p.add_argument("--no-zoom", action="store_true", help="켄번스(확대/이동) 효과 끄기")
    p.add_argument("--bgm", help="배경음악 파일 (mp3 등)")
    p.add_argument("--font", help="자막 폰트 파일(.ttf/.ttc)")


def _add_publish_args(p: argparse.ArgumentParser, need_title: bool) -> None:
    p.add_argument("--platforms", default="all",
                   help=f"게시할 플랫폼, 쉼표 구분 또는 all ({','.join(PUBLISHERS)})")
    if need_title:
        p.add_argument("--title", required=True, help="게시 제목")
    p.add_argument("--description", default="", help="설명/본문")
    p.add_argument("--tags", default="", help="해시태그, 쉼표 구분. 예: 여행,브이로그")
    p.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shortsmaker", description="사진으로 숏폼 영상 만들고 여러 플랫폼에 올리기")
    parser.add_argument("--config", help="설정 파일 경로 (기본 config.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make", help="사진으로 영상 만들기")
    _add_video_args(make)

    pub = sub.add_parser("publish", help="만든 영상을 플랫폼에 올리기")
    pub.add_argument("video")
    _add_publish_args(pub, need_title=True)

    auto = sub.add_parser("auto", help="영상 만들기 + 바로 올리기")
    _add_video_args(auto)
    _add_publish_args(auto, need_title=False)

    sub.add_parser("youtube-auth", help="YouTube 계정 로그인 (최초 1회)")

    web = sub.add_parser("web", help="웹 화면 실행")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    return parser


def _make(args, cfg) -> Path:
    opts = VideoOptions.from_dict(cfg.get("video"))
    for attr, value in [("title", args.title), ("seconds_per_image", args.seconds),
                        ("transition", args.transition), ("fit", args.fit),
                        ("bgm_path", args.bgm), ("font_path", args.font)]:
        if value is not None:
            setattr(opts, attr, value)
    if args.captions:
        opts.captions = _split(args.captions, "|")
    if args.no_zoom:
        opts.ken_burns = False

    images = resolve_inputs(args.inputs)
    out = Path(args.output or f"output/short_{datetime.now():%Y%m%d_%H%M%S}.mp4")
    print(f"사진 {len(images)}장으로 영상 만드는 중...")
    make_video(images, out, opts,
               progress_cb=lambda p: print(f"\r  {p * 100:5.1f}%", end="", flush=True))
    print(f"\n완료: {out}")
    return out


def _publish(video: Path, args, cfg) -> int:
    if not args.title:
        print("게시하려면 --title 이 필요합니다.", file=sys.stderr)
        return 2
    meta = PostMeta(args.title, args.description, _split(args.tags, ","), args.privacy)
    results = publish_all(video, meta, _platforms(args.platforms), cfg)
    failed = 0
    for r in results:
        label = PLATFORM_LABELS.get(r.platform, r.platform)
        if r.ok:
            print(f"[성공] {label}: {r.url or r.post_id}")
        else:
            failed += 1
            print(f"[실패] {label}: {r.error}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    try:
        return _run(args, cfg)
    except (OSError, RuntimeError, ValueError) as e:
        print(f"\n오류: {e}", file=sys.stderr)
        return 1


def _run(args, cfg) -> int:

    if args.command == "make":
        _make(args, cfg)
        return 0
    if args.command == "publish":
        return _publish(Path(args.video), args, cfg)
    if args.command == "auto":
        return _publish(_make(args, cfg), args, cfg)
    if args.command == "youtube-auth":
        from .platforms.youtube import get_credentials
        yt = cfg.get("youtube") or {}
        get_credentials(yt.get("client_secrets_file", "client_secret.json"),
                        yt.get("token_file", "youtube_token.json"), interactive=True)
        print("YouTube 로그인 완료")
        return 0
    if args.command == "web":
        import uvicorn
        from .web.app import create_app
        uvicorn.run(create_app(cfg), host=args.host, port=args.port)
        return 0
    return 1
