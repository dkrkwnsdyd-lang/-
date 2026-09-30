"""MULTI PLATFORM ADAPTER: 마스터 1개 -> 플랫폼별 버전 (CTA 장면, 음량, 인코딩, 문구가 다름).

플랫폼 규칙은 brain/system/platform_rules.yaml 의 profile 만 고치면 된다.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .. import brain
from ..platforms.base import truncate
from ..video import ffmpeg_exe
from .director import product_short, strip_marks


VOICE = (
    "말투: 광고 문구가 아니라 친구에게 보여주며 말하는 듯한 자연스러운 한국어 대화체(~네, ~더라, ~거든요, ㅋㅋ 가끔). "
    "구조: (1) 공감/발견 한 줄 도입 (2) 눈에 보이는 포인트 (3) 귀여운/눈에 띄는 디테일 한 줄 (4) 가볍게 마무리하는 한 줄. "
    "한 줄은 짧게(20자 안팎), 줄바꿈을 자주 쓰고, 이모지는 전체에 1~2개만. 느낌표 남발, '최고/꼭 사세요/강추' 같은 광고 말투 금지. "
    "예시(형식만 참고, 내용은 복사 금지): '집에 뭔가 하나 허전했는데ㅋㅋ / 화분 하나 걸었더니 분위기 확 달라짐🌱 / 그네 타고 있는 것도 귀엽고 / 이런 게 은근 포인트네✨'. "
    "주의: 위 예시처럼 '했더니 달라짐' 같은 경험담은 '직접 써본 느낌(사용자 작성)'이 있을 때만 그 내용으로 쓰고, 없으면 사진에 보이는 것과 특징만 가볍게 말한다. "
)


def profiles() -> dict:
    return brain.system("platform_rules")["profiles"]


def _tags(p, profile: dict) -> list[str]:
    lo, hi = profile["hashtag_style"]["count"]
    base = list(profile["hashtag_style"].get("always", []))
    brand = next((w for w in p.name.split() if w.isascii() and w.isalpha() and len(w) > 2), "")
    cands = [product_short(p.name), brand, p.category_hint]
    for c in cands:
        c = re.sub(r"[^\w가-힣]", "", (c or ""))   # 해시태그는 하이픈/기호에서 끊긴다 (M-Circle -> MCircle)
        if c and c not in base and len(c) <= 12 and not re.search(r"\d", c):
            base.append(c)
    return [f"#{t}" for t in base[:hi]] if hi else []


def platform_copy(plan, p, router=None, vision=None, with_report: bool = False):
    """플랫폼마다 다른 문구. LLM 이 있으면 LLM(근거 검증 통과 시), 없거나 검증 실패면 템플릿 (동일 문구 복사 금지)."""
    result = _platform_copy(plan, p, router, vision)
    return result if with_report else result[0]


def _platform_copy(plan, p, router, vision):
    from . import grounding
    disclosure = brain.policy("korea")["disclosure_rules"].get(p.affiliate) if p.affiliate != "NONE" else ""
    hook = strip_marks(plan.hook_candidates[0]["text"]) if plan.hook_candidates else p.name
    feats = [f for f in p.features[:3]]
    prof = profiles()
    template = lambda: _template_copy(plan, p, hook, feats, prof)   # noqa: E731
    if router is not None and router.has_real("llm"):
        facts = grounding.allowed_facts(p, vision)

        def produce(feedback):
            system = ("한국어 쇼핑 쇼츠 게시 문구 작성. 플랫폼마다 말투/길이/해시태그 수가 달라야 하며 같은 문장을 반복하지 않는다. " + VOICE +
                      "입력에 없는 판매량/후기수/순위/효능/인증은 쓰지 않는다. " + grounding.RULES_FOR_WRITER + " JSON: "
                      '{"youtube":{"title","description"},"instagram":{"caption"},"tiktok":{"caption"},"threads":{"post"}}'
                      + ("\n" + feedback if feedback else ""))
            job = {"name_exact": p.name, "allowed_facts": facts, "hook": hook, "price": p.price,
                   "styles": {k: {"hook_style": v["hook_style"], "cta_style": v["cta_style"],
                                  "description_style": v["description_style"], "hashtags": v["hashtag_style"]}
                              for k, v in prof.items()}}
            res = router.run("llm", "json", system=system, user=json.dumps(job, ensure_ascii=False))
            if res.provider == "local":
                raise RuntimeError("LLM 사용 불가")
            return res.value

        def lines(d):
            out = []
            for v in d.values():
                if isinstance(v, dict):
                    out += [str(x) for x in v.values() if isinstance(x, str)]
            return out

        data, report = grounding.generate_grounded(router, produce, lines, facts, p.name, lambda: None)
        if data is not None:
            return _finalize(data, disclosure, p, prof), report
        return template(), report
    return template(), {"attempts": [], "final": "template"}


def _casual_post(p, short: str, feats: list[str]) -> str:
    """LLM 없이도 대화체로: 공감/발견 -> 포인트 -> 사용자 한 줄 -> 마무리. 입력에 없는 경험/효과는 쓰지 않는다."""
    lines = [f"{p.problem.rstrip('.?!')}… 저만 그런 거 아니죠?" if p.problem else f"{short} 하나 발견했는데ㅋㅋ"]
    if feats:
        lines.append(f"{feats[0]} 이 부분이 눈에 들어오네요")
    if getattr(p, "my_take", ""):
        lines.append(p.my_take.strip())
    elif len(feats) > 1:
        lines.append(f"{feats[1]}도 있어요")
    lines.append("써본 분 의견 궁금해요")
    return "\n".join(lines)


def _template_copy(plan, p, hook, feats, prof):
    disclosure = brain.policy("korea")["disclosure_rules"].get(p.affiliate) if p.affiliate != "NONE" else ""
    short = product_short(p.name)
    bullet = "\n".join(f"· {f}" for f in feats)
    data = {
        "youtube": {"title": hook if short in hook else f"{hook} | {short}",
                    "description": f"{p.name}\n\n{bullet}\n\n{prof['youtube']['cta_text']}"},
        "instagram": {"caption": f"{hook}\n.\n{p.name}\n{bullet}\n.\n{prof['instagram']['cta_text']} 🛒"},
        "tiktok": {"caption": f"{short} 이거 봤어요? {feats[0] if feats else ''} {prof['tiktok']['cta_text']}".strip()},
        "threads": {"post": _casual_post(p, short, feats)},
    }
    return _finalize(data, disclosure, p, prof)


def _finalize(data: dict, disclosure: str, p, prof: dict) -> dict:
    out = {}
    for pf in ("youtube", "instagram", "tiktok", "threads"):
        d = dict(data.get(pf) or {})
        tags = " ".join(_tags(p, prof[pf]))
        if pf == "youtube":
            title = d.get("title", p.name)
            if "#shorts" not in title.lower():
                title = f"{title} #Shorts"
            desc = d.get("description", "")
            if disclosure:
                desc = f"{disclosure}\n\n{desc}"
            out[pf] = {"title": truncate(title, 100), "description": truncate(f"{desc}\n\n{tags}".strip(), 5000)}
        else:
            key = "post" if pf == "threads" else "caption"
            body = d.get(key) or d.get("caption") or d.get("post") or p.name
            if disclosure:
                body = f"{disclosure}\n{body}"
            limit = 500 if pf == "threads" else 2200
            out[pf] = {key: truncate(f"{body}\n{tags}".strip() if tags else body, limit)}
        out[pf]["hashtags"] = tags
        out[pf]["affiliate_disclosure"] = disclosure or ""
    return out


def export_platform(video_only: Path, audio: Path, out: Path, profile: dict, max_duration: float | None = None) -> Path:
    """음량(LUFS) 정규화 + 플랫폼 인코딩 프리셋으로 최종 파일 생성."""
    ex = profile["export_preset"]
    lufs = profile["audio_rule"]["loudness_lufs"]
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-i", str(video_only), "-i", str(audio),
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", str(ex["crf"]),
           "-maxrate", ex["maxrate"], "-bufsize", ex["maxrate"], "-pix_fmt", "yuv420p", "-r", "30",
           "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000", "-ac", "2",
           "-c:a", "aac", "-b:a", ex["audio_bitrate"], "-shortest", "-movflags", "+faststart"]
    if max_duration:
        cmd += ["-t", f"{max_duration:.2f}"]
    cmd.append(str(out))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"플랫폼 export 실패: {r.stderr[-400:]}")
    return out


def concat(parts: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    r = subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)], capture_output=True, text=True)
    lst.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"concat 실패: {r.stderr[-300:]}")
    return out
