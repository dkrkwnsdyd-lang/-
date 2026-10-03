"""기존 영상 제작 파이프라인과 연결: UGC 스토리보드 → director_data(beats) + Scene 별 AI 영상 프롬프트.

기존 Renderer/Storyboard/Preview/Quality 흐름은 그대로 쓴다. AI 영상 생성은 기존 비용 제어(ECONOMY/BALANCED/PREMIUM, 사용자 동의 [AI 장면 생성])를 그대로 따르며,
검증된 영상 provider 가 없으면 제품 사진 기반으로 렌더된다 (프롬프트는 패키지로 남음).
"""
from __future__ import annotations

STAGE_TO_BEAT = {"hook": "hook", "problem": "problem", "agitation": "problem", "solution": "reveal", "demonstration": "demo", "proof": "benefit", "benefit": "benefit", "cta": "cta"}
STAGE_ROLE = {"hook": "hook", "problem": "pain", "agitation": "pain_emotion", "solution": "reveal", "demonstration": "demo", "proof": "proof", "benefit": "result", "cta": "cta"}


def to_director_data(session: dict) -> dict:
    pkg, board = session["package"], session["storyboard"]
    beats = []
    for sp, sc in zip(pkg["scenes"], board["scenes"]):
        beats.append({"beat": STAGE_TO_BEAT[sc["stage"]], "story_role": STAGE_ROLE[sc["stage"]], "tts_line": sc["voice_over"], "caption": sc["caption"],
                      "feature": None, "visual_prompt": sp["video_prompt"]})
    # director 규칙: reveal 이 반드시 필요 (없으면 solution 이 없는 구성이라 hook 다음에 reveal 장면을 하나 만든다)
    if not any(b["beat"] == "reveal" for b in beats):
        beats.insert(1, {"beat": "reveal", "story_role": "reveal", "tts_line": f"바로 이 제품이에요", "caption": "바로 이 [[제품]]", "feature": None, "visual_prompt": ""})
    concept = pkg["concept"]
    return {"angles": [], "best_angle": "convenience", "story_pattern": "PROBLEM_SOLUTION" if any(b["beat"] == "problem" for b in beats) else "DISCOVERY",
            "hook_candidates": [{"type": "ugc_reference", "text": concept["hook"], "caption": beats[0]["caption"]}], "beats": beats,
            "tension": concept.get("main_usp", ""), "payoff": concept.get("selling_angle", {}) and concept["selling_angle"].get("premise", ""),
            "_director": f"ugc_reference:{concept['id']}", "_grounding": {"final": "ugc_reference"}}


def scene_prompts(session: dict) -> list[str]:
    return [sp["video_prompt"] for sp in session["package"]["scenes"]]
