"""Preview Conversion Audit 재평가 회귀 검사. 외부 API/유료 호출 없음."""
from copy import deepcopy
from types import SimpleNamespace

from shortsmaker.studio.product import ProductInput
from shortsmaker.studio.strategy import make_ctx, run_strategy
from shortsmaker.studio.strategy.preview_review import recheck_edited_plan, requires_recheck


def fixture():
    ctx = make_ctx(ProductInput(name="보온보냉 텀블러", features=["원터치 뚜껑", "세척이 쉬운 넓은 입구"],
                                problem="텀블러 뚜껑 열기가 번거로워요", target="직장인"))
    state = run_strategy(None, ctx, auto=False)
    scenes = [SimpleNamespace(scene_id=s["scene_id"], beat=s["beat"],
                              tts_line=s["narration"], caption=s["caption"],
                              duration=s["duration"]) for s in state["final_script"]["scenes"]]
    return ctx, state, SimpleNamespace(scenes=scenes)


def test_only_applied_text_and_structure_edits_trigger_recheck():
    assert not requires_recheck({"applied": []})
    assert not requires_recheck({"applied": [{"what": "이미지 교체"}]})
    assert requires_recheck({"applied": [{"what": "자막"}]})
    assert requires_recheck({"applied": [{"what": "삭제"}]})


def test_preview_review_recalculates_and_blocks_unsafe_hook():
    ctx, state, plan = fixture()
    old = deepcopy(state)
    plan.scenes[0].tts_line = "대박 역대급! 꼭 보세요 진짜 최고 90% 할인입니다"
    revised = recheck_edited_plan(state, plan, ctx)
    assert revised["preview_review"]["status"] == "RECHECKED"
    assert revised["conversion_audit"]["status"] == "RECHECKED"
    assert revised["final_script"]["scenes"][0]["narration"] == plan.scenes[0].tts_line
    assert not revised["gate"]["passed"]
    assert revised["conversion_audit"]["scores"] != old["conversion_audit"]["scores"]
    assert state == old  # 이전 승인된 초안 자체는 불변


def test_preview_review_caption_is_audited_too():
    ctx, state, plan = fixture()
    plan.scenes[1].caption = "오늘만 90% 할인 재고 한정"
    revised = recheck_edited_plan(state, plan, ctx)
    assert revised["final_script"]["scenes"][1]["caption"] == plan.scenes[1].caption
    assert not revised["gate"]["passed"]
    assert any(f["code"] == "unproven_claim" for f in revised["gate"]["failures"])


def test_preview_review_unmappable_scene_fails_closed():
    ctx, state, plan = fixture()
    plan.scenes[0].scene_id = "S9999"
    plan.scenes[0].beat = "nonsense"
    revised = recheck_edited_plan(state, plan, ctx)
    assert revised["conversion_audit"]["status"] == "STALE"
    assert not revised["gate"]["passed"]
    assert revised["gate"]["failures"][0]["code"] == "audit_scene_mismatch"
