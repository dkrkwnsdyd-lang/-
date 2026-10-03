"""REAL_UGC: 사용자가 직접 찍은 영상에서 쓸 구간 후보를 뽑아 Storyboard 장면에 배치한다 (AI 영상보다 우선, 비용 0).

분석은 단계적: (1) 로컬 측정(선명도/밝기/흔들림 -> best_window)은 항상, (2) Vision 이 있으면 구간 대표 프레임에 '무슨 행동인지/제품이 보이는지/얼굴이 나오는지' 태그.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import clips as clips_mod
from ...video import ffmpeg_exe

ACTIONS = ("hold", "use", "press", "closeup", "unbox", "wear", "other")
ACTION_KO = {"hold": "제품을 손에 들고 보여주는 장면", "use": "제품을 사용하는 장면", "press": "버튼을 누르거나 조작하는 장면", "closeup": "제품 클로즈업",
             "unbox": "언박싱 장면", "wear": "착용 장면", "other": "기타"}
PREFER = {"DEMO": ("use", "press", "hold"), "FEATURE": ("press", "closeup", "use"), "PRODUCT_REVEAL": ("hold", "unbox", "closeup"),
          "BENEFIT": ("use", "wear", "hold"), "PROOF": ("use", "wear"), "PROBLEM": ("other",)}
ELIGIBLE_ORDER = ("DEMO", "PRODUCT_REVEAL", "FEATURE", "BENEFIT")
MAX_REAL_SCENES = 3
BEAT_OF = {"DEMO": "demo", "FEATURE": "demo", "BENEFIT": "benefit", "PRODUCT_REVEAL": "reveal"}     # 하이라이트 보정용 (사용 중인 구간 우대)

TAG_SYSTEM = ('You see one frame from the middle of a candidate segment of a user-shot product video. Answer JSON only: '
              '{"action":"hold|use|press|closeup|unbox|wear|other","product_visible":true,"face_visible":false,"desc":"Korean, max 20 chars"}')


def _reasons(info: dict, w: dict, sc) -> list[str]:
    from .. import highlights
    return highlights.explain(info, w["start"], w["dur"], BEAT_OF.get(sc.scene_type))


def candidate_windows(info: dict, dur: float, n: int = 3) -> list[dict]:
    """겹치지 않는 후보 구간 n 개 (점수 높은 순)."""
    used, out = [], []
    for _ in range(n):
        w = clips_mod.best_window(info, dur, used)
        if not w:
            break
        used.append((w["start"], w["start"] + w["dur"]))
        out.append(w)
    return out


def _frame(path: str, t: float, dst: Path) -> str | None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale='min(512,iw)':-2",
                    "-q:v", "3", str(dst)], capture_output=True)
    return str(dst) if dst.exists() else None


def tag_window(router, info: dict, w: dict, work_dir: Path) -> dict:
    """Vision 으로 구간 태그. 없으면 빈 태그(로컬 점수만 사용)."""
    if router is None or not router.has_real("vision"):
        return {}
    fp = _frame(info["path"], w["start"] + w["dur"] / 2, work_dir / f"tag_{Path(info['path']).stem}_{int(w['start'] * 10)}.jpg")
    if not fp:
        return {}
    try:
        v = router.run("vision", "json", system=TAG_SYSTEM, user="Tag this frame.", images=[fp], temperature=0).value
    except Exception:
        return {}
    if not isinstance(v, dict) or v.get("action") not in ACTIONS:
        return {}
    return {"action": v["action"], "product_visible": bool(v.get("product_visible", True)), "face_visible": bool(v.get("face_visible", False)),
            "desc": str(v.get("desc") or ACTION_KO.get(v["action"], ""))[:30]}


def place(scenes: list, infos: list[dict], router=None, work_dir: Path | None = None) -> list[dict]:
    """장면에 실제 영상 구간 배치. scene.source_type='REAL_UGC', visual_source 에 구간 정보, layout 은 demo(사용/조작) 또는 lifestyle."""
    if not infos:
        return []
    work_dir = work_dir or Path("data/tmp_real")
    elig = [s for s in scenes if s.scene_type in ELIGIBLE_ORDER]
    elig.sort(key=lambda s: ELIGIBLE_ORDER.index(s.scene_type))
    used: dict[int, list[tuple[float, float]]] = {i["index"]: [] for i in infos}
    report = []
    for sc in elig:
        if len(report) >= MAX_REAL_SCENES:
            break
        cands = []
        for info in infos:
            for w in candidate_windows_avoid(info, max(1.4, sc.duration), used[info["index"]], beat=BEAT_OF.get(sc.scene_type)):
                tag = tag_window(router, info, w, work_dir) if router is not None else {}
                pref = PREFER.get(sc.scene_type, ())
                bonus = 0.25 * (len(pref) - pref.index(tag["action"])) / max(len(pref), 1) if tag.get("action") in pref else 0.0
                if tag and not tag.get("product_visible", True):
                    continue                                    # 제품이 안 보이는 구간은 쓰지 않는다
                cands.append((w["score"] + bonus, info, w, tag))
        if not cands:
            continue
        _, info, w, tag = max(cands, key=lambda c: c[0])
        used[info["index"]].append((w["start"], w["start"] + w["dur"]))
        action = tag.get("action")
        sc.source_type = "REAL_UGC"
        sc.layout = "demo" if (action in ("use", "press") or (not action and sc.scene_type == "DEMO")) else "lifestyle"
        sc.visual_source = {"kind": "user_video", "path": info["path"], "tier": 1, "clip_start": w["start"], "clip_aspect": info["aspect"],
                            "window_dur": w["dur"], "tag": tag, "reason": "사용자가 올린 실제 영상 (AI 생성 비용 없음)",
                            "fallback_path": sc.visual_source.get("fallback_path") or sc.visual_source.get("path")}
        sc.duration = round(min(sc.duration, w["dur"]), 2) if w["dur"] >= 1.2 else sc.duration
        sc.ai = {}
        report.append({"scene_id": sc.scene_id, "scene_type": sc.scene_type, "clip": Path(info["path"]).name, "start": w["start"], "dur": w["dur"],
                      "score": w["score"], "tag": tag.get("desc") or "", "action": action,
                      **({"reasons": _reasons(info, w, sc)} if info.get("sig") else {})})
    return report


def candidate_windows_avoid(info: dict, dur: float, avoid: list, n: int = 2, beat: str | None = None) -> list[dict]:
    out, used = [], list(avoid)
    for _ in range(n):
        w = clips_mod.best_window(info, dur, used)
        if not w:
            break
        used.append((w["start"], w["start"] + w["dur"]))
        out.append(w)
    return out
