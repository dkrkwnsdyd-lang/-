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


def test_actual_preview_to_render_blocks_unsupported_user_edits(tmp_path):
    """Integration: API-compatible state reuse must not bypass the new gate."""
    from product_fixtures import PRODUCTS, make_photos
    from shortsmaker.db import DB
    from shortsmaker.studio.pipeline import run_job

    item = PRODUCTS["kitchen_tumbler"]
    photos = make_photos("kitchen_tumbler", tmp_path / "images", 3)
    base = {"name": item["name"], "features": item["features"], "problem": item["problem"],
            "category_hint": "주방", "photos": photos, "video_style": "STORY_AD"}
    db = DB(tmp_path / "data.sqlite")
    preview = run_job({**base, "preview": True}, "FAST", ["youtube"],
                      out_root=tmp_path / "out", db=db, render=(270, 480, 10))
    assert preview["status"] == "PREVIEW_READY", preview.get("error")
    hook_id = preview["storyboard"]["scenes"][0]["scene_id"]
    edited = {"scenes": {hook_id: {"narration": "역대급 무조건 꼭 사세요 90% 할인"}}}

    blocked = run_job({**base, "preview": False, "director_data": preview["director_data"],
                       "strategy_state": preview["strategy"], "edits": edited},
                      "FAST", ["youtube"], out_root=tmp_path / "out", db=db,
                      render=(270, 480, 10))
    assert blocked["status"] == "STRATEGY_BLOCKED", blocked.get("error")
    assert blocked["blocked"]["gate"]["failures"]
    assert not list((tmp_path / "out" / blocked["job_id"]).rglob("*.mp4"))
