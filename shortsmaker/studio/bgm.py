"""BGM 분석: 폴더(카테고리별 하위 폴더 가능)의 음악 파일을 훑어 쇼츠에 쓸 만한지 측정한다.

사용:  python -m shortsmaker.studio.bgm "<폴더>" [결과.csv]
측정(모두 계산값이며 저작권/사용 허가 여부는 판단하지 않는다):
- duration      길이(초)
- rms_db/peak_db 평균/최대 음량(dBFS). rms 가 너무 낮으면 작게, 너무 높으면 음성을 덮는다
- lead_silence/tail_silence 앞뒤 무음(초)
- bpm           박자 추정(60~180, 신뢰도 낮으면 빈 값). 추정이므로 ±몇 BPM 오차 가능
- bpm_conf      박자 추정 신뢰도 0~1
- seam_db       반복(루프)할 때 끝→처음 이음매의 음량 차이(dB). 작을수록 자연스러움
- loudness_range 음량 변화 폭(dB). 크면 갑자기 커지는 곡
- fit_score     쇼츠 배경음 적합도 0~100 (규칙 점수: 길이/음량/무음/이음매/변화 폭)
- flags         문제 표시
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

from .audio import SR, decode_audio

EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
TARGET_RMS_DB = (-26.0, -14.0)          # 쇼츠 배경음으로 무난한 평균 음량 범위 (믹스에서 0.2~0.4 배로 낮춰 씀)


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-6)))


def _win_rms(y: np.ndarray, win: int) -> np.ndarray:
    n = len(y) // win
    if n == 0:
        return np.array([float(np.sqrt(np.mean(y ** 2)))]) if len(y) else np.array([0.0])
    return np.sqrt(np.mean(y[: n * win].reshape(n, win) ** 2, axis=1))


def estimate_bpm(y: np.ndarray) -> tuple[float | None, float]:
    """에너지 변화(온셋)의 자기상관으로 박자 추정. (bpm, 신뢰도)"""
    y = y[: SR * 90]
    hop = 512
    n = len(y) // hop
    if n < 200:
        return None, 0.0
    env = np.sqrt(np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1))
    onset = np.maximum(np.diff(env), 0)
    onset = onset - onset.mean()
    if onset.std() < 1e-9:
        return None, 0.0
    ac = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    fps = SR / hop
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)
    seg = ac[lo:hi + 1]
    if len(seg) < 3 or ac[0] <= 0:
        return None, 0.0
    k = int(np.argmax(seg)) + lo
    bpm = 60 * fps / k
    while bpm < 80:                       # 반 박자/두 배 박자 혼동 보정 (80~160 범위로)
        bpm *= 2
    while bpm > 160:
        bpm /= 2
    conf = float(np.clip(ac[k] / ac[0] * 2.0, 0, 1))
    return round(bpm, 1), round(conf, 2)


def analyze(path: str | Path) -> dict:
    p = Path(path)
    y = decode_audio(p)
    dur = len(y) / SR
    out = {"file": p.name, "category": p.parent.name, "path": str(p), "duration": round(dur, 1)}
    if dur < 1.0:
        return {**out, "error": "너무 짧거나 읽을 수 없음", "fit_score": 0, "flags": "unreadable"}
    r = _win_rms(y, int(SR * 0.1))
    active = np.where(r > 10 ** (-50 / 20))[0]            # -50dB 보다 큰 구간
    lead = float(active[0] * 0.1) if len(active) else dur
    tail = float((len(r) - 1 - active[-1]) * 0.1) if len(active) else dur
    rms_all = float(np.sqrt(np.mean(y ** 2)))
    seg_db = np.array([_db(v) for v in _win_rms(y, SR)])      # 1초 단위 음량
    seg_db = seg_db[seg_db > -60]
    lrange = float(np.percentile(seg_db, 95) - np.percentile(seg_db, 5)) if len(seg_db) > 4 else 0.0
    head = float(np.sqrt(np.mean(y[: SR // 2] ** 2)))
    end = float(np.sqrt(np.mean(y[-SR // 2:] ** 2)))
    seam = abs(_db(end) - _db(head)) if min(head, end) > 1e-5 else 40.0
    bpm, conf = estimate_bpm(y)
    flags = []
    score = 100.0
    if dur < 12:
        flags.append("짧음(<12초: 반복 필요)"); score -= 25
    elif dur < 25:
        flags.append("영상보다 짧을 수 있음(<25초)"); score -= 8
    rms_db = _db(rms_all)
    if rms_db < TARGET_RMS_DB[0]:
        flags.append("음량 작음"); score -= min(25, (TARGET_RMS_DB[0] - rms_db) * 3)
    if rms_db > TARGET_RMS_DB[1]:
        flags.append("음량 큼(음성 덮음)"); score -= min(30, (rms_db - TARGET_RMS_DB[1]) * 4)
    if lead > 0.6:
        flags.append(f"앞 무음 {lead:.1f}s"); score -= min(15, lead * 5)
    if tail > 1.5:
        flags.append(f"뒤 무음 {tail:.1f}s"); score -= min(10, tail * 2)
    if seam > 10:
        flags.append(f"반복 이음매 큼({seam:.0f}dB)"); score -= min(15, (seam - 10) * 1.0)
    if lrange > 12:
        flags.append(f"음량 변화 큼({lrange:.0f}dB)"); score -= min(20, (lrange - 12) * 2.5)
    if conf < 0.15:
        flags.append("박자 불확실")
    out.update({"rms_db": round(rms_db, 1), "peak_db": round(_db(float(np.max(np.abs(y)))), 1), "lead_silence": round(lead, 1),
                "tail_silence": round(tail, 1), "bpm": bpm if conf >= 0.15 else "", "bpm_conf": conf, "seam_db": round(seam, 1),
                "loudness_range": round(lrange, 1), "fit_score": int(max(0, min(100, round(score)))), "flags": "; ".join(flags)})
    return out


def scan(folder: str | Path, progress=None) -> list[dict]:
    files = sorted(f for f in Path(folder).rglob("*") if f.suffix.lower() in EXTS)
    rows = []
    for i, f in enumerate(files, 1):
        try:
            rows.append(analyze(f))
        except Exception as e:                                  # 한 파일이 깨져도 나머지는 계속
            rows.append({"file": f.name, "category": f.parent.name, "path": str(f), "error": str(e)[:80], "fit_score": 0, "flags": "error"})
        if progress:
            progress(i, len(files), f.name)
    return rows


FIELDS = ["category", "file", "duration", "rms_db", "peak_db", "lead_silence", "tail_silence", "bpm", "bpm_conf", "seam_db",
          "loudness_range", "fit_score", "flags", "error", "path"]


def write_csv(rows: list[dict], out: str | Path) -> None:
    with open(out, "w", newline="", encoding="utf-8-sig") as f:          # utf-8-sig: 엑셀에서 한글이 안 깨짐
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def summary(rows: list[dict]) -> str:
    ok = [r for r in rows if not r.get("error")]
    cats: dict[str, list] = {}
    for r in ok:
        cats.setdefault(r["category"], []).append(r)
    lines = [f"분석 {len(rows)}곡 (읽기 실패 {len(rows) - len(ok)}곡)"]
    for c, rs in sorted(cats.items()):
        good = [r for r in rs if r["fit_score"] >= 75]
        bpms = [r["bpm"] for r in rs if r.get("bpm") != ""]
        lines.append(f"- {c}: {len(rs)}곡, 적합(75점 이상) {len(good)}곡, 평균 길이 {np.mean([r['duration'] for r in rs]):.0f}초"
                     + (f", 박자 중앙값 {np.median(bpms):.0f}BPM" if bpms else ""))
    return "\n".join(lines)


# ------------------------------------------------------------------ 라이브러리: 색인 + 자동 선택
import hashlib
import json
import os

INDEX_PATH = Path("data/bgm_index.json")
STYLE_BPM = {"FAST_COMMERCE": 124, "STORY_AD": 84, "UGC_REVIEW": 92, "STANDARD": 100}
# 상품 카테고리(strategy.common.category_key) -> 어울리는 음악 폴더 이름(앞쪽이 우선). 폴더 이름에 이 단어가 들어 있으면 해당
CATEGORY_FOLDERS = {
    "electronics": ["IT", "AI", "공통"], "kitchen": ["요리", "레시피", "라이프해킹", "공통"], "living": ["라이프해킹", "상식", "공통"],
    "fitness": ["건강", "운동", "동기부여", "공통"], "beauty": ["뷰티", "패션", "공통"], "camping": ["여행", "라이프해킹", "공통"],
    "general": ["공통", "라이프해킹"],
}
MIN_FIT = 75


def find_library(project_root: str | Path = ".") -> Path | None:
    """SHORTSMAKER_BGM_DIR 환경변수, 없으면 프로젝트 폴더 안에서 이름에 'BGM'(대소문자 무관)이 들어간 폴더."""
    env = os.environ.get("SHORTSMAKER_BGM_DIR", "").strip().strip('"')
    if env and Path(env).is_dir():
        return Path(env)
    root = Path(project_root)
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if d.is_dir() and "bgm" in d.name.lower() and not d.name.startswith("."):
            return d
    return None


def build_index(folder: str | Path, index_path: str | Path = INDEX_PATH, progress=None) -> list[dict]:
    """분석 결과를 JSON 으로 저장. 파일 크기/수정시각이 같은 곡은 다시 분석하지 않는다."""
    ip = Path(index_path)
    old = {}
    if ip.exists():
        try:
            old = {r["path"]: r for r in json.loads(ip.read_text(encoding="utf-8")).get("tracks", [])}
        except (ValueError, KeyError):
            old = {}
    files = sorted(f for f in Path(folder).rglob("*") if f.suffix.lower() in EXTS)
    rows = []
    for i, f in enumerate(files, 1):
        st = f.stat()
        sig = f"{st.st_size}:{int(st.st_mtime)}"
        r = old.get(str(f))
        if not (r and r.get("sig") == sig):
            try:
                r = analyze(f)
            except Exception as e:
                r = {"file": f.name, "category": f.parent.name, "path": str(f), "error": str(e)[:80], "fit_score": 0, "flags": "error"}
            r["sig"] = sig
        rows.append(r)
        if progress:
            progress(i, len(files), f.name)
    ip.parent.mkdir(parents=True, exist_ok=True)
    ip.write_text(json.dumps({"folder": str(folder), "tracks": rows}, ensure_ascii=False), encoding="utf-8")
    return rows


def load_index(index_path: str | Path = INDEX_PATH) -> list[dict]:
    try:
        return json.loads(Path(index_path).read_text(encoding="utf-8")).get("tracks", [])
    except (OSError, ValueError):
        return []


def _bpm_gap(bpm, target: float) -> float:
    if bpm in ("", None):
        return 25.0                                    # 박자를 모르면 중간 정도 불이익
    b = float(bpm)
    return min(abs(b - target), abs(b / 2 - target), abs(b * 2 - target))      # 반/두 배 박자 혼동 허용


def choose(tracks: list[dict], category: str, style: str, seed: str = "") -> dict | None:
    """카테고리 폴더(우선순위) + 적합도 75 이상 + 스타일 박자에 가까운 곡들 중에서, seed 로 결정적으로 하나 고른다."""
    ok = [t for t in tracks if not t.get("error") and t.get("fit_score", 0) >= MIN_FIT and t.get("duration", 0) >= 20]
    if not ok:
        return None
    words = CATEGORY_FOLDERS.get(category, CATEGORY_FOLDERS["general"])
    target = STYLE_BPM.get(style, 100)
    for rank, w in enumerate(words):
        pool = [t for t in ok if w.lower() in t["category"].lower()]
        if pool:
            pool.sort(key=lambda t: (_bpm_gap(t.get("bpm"), target), -t["fit_score"], t["file"]))
            top = pool[:3]                                  # 박자가 가장 가까운 3곡 중 seed 로 선택 (같은 상품은 같은 곡)
            pick = top[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(top)]
            return {**pick, "reason": f"카테고리 폴더 '{pick['category']}' · 스타일 박자 {target}BPM 에 가까운 곡 (곡 박자 {pick.get('bpm') or '미상'}) · 적합도 {pick['fit_score']}"}
    return None


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    folder = Path(argv[0])
    out = Path(argv[1]) if len(argv) > 1 else Path("bgm_report.csv")
    if not folder.exists():
        print(f"폴더를 찾을 수 없어요: {folder}")
        return 1
    rows = scan(folder, lambda i, n, name: print(f"\r{i}/{n} {name[:40]:40}", end="", flush=True))
    print()
    write_csv(rows, out)
    try:
        build_index(folder, INDEX_PATH)           # 앱이 곡을 자동으로 고를 때 쓰는 색인 (data/bgm_index.json)
        print(f"앱용 색인 저장: {INDEX_PATH.resolve()}")
    except OSError as e:
        print(f"색인 저장 실패: {e}")
    print(summary(rows))
    print(f"\n표 저장: {out.resolve()}  (엑셀로 열 수 있어요)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
