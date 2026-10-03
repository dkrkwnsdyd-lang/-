"""AI_PRODUCT_UGC prompt compiler regression tests.

These tests are intentionally provider-free: they verify prompt/routing safety without
making a paid video API call.
"""
from types import SimpleNamespace

from shortsmaker.studio.presenter import product_ugc


class _Identity:
    def lock_prompt(self):
        return "LOCKED ITEM: same navy body, white logo, and same side button."


def _ctx(features=None):
    return SimpleNamespace(
        p=SimpleNamespace(
            name="테스트 상품",
            features=list(features or []),
        )
    )


def _scene(kind="AI_PRODUCT_UGC", scene_type="DEMO", prompt="Base visual prompt"):
    return SimpleNamespace(
        scene_type=scene_type,
        ai={"kind": kind, "prompt": prompt, "settings": {}},
    )


def test_apply_only_targets_ai_product_ugc():
    product_scene = _scene()
    presenter_scene = _scene(kind="AI_PRESENTER")
    before = dict(presenter_scene.ai)

    assert product_ugc.apply_to_scene(
        product_scene,
        ctx=_ctx(["측면 버튼"]),
        identity=_Identity(),
        reference_prompt="Natural handheld close-up with a slow pan.",
    )
    assert not product_ugc.apply_to_scene(
        presenter_scene,
        ctx=_ctx(["측면 버튼"]),
        identity=_Identity(),
        reference_prompt="Natural handheld close-up with a slow pan.",
    )
    assert presenter_scene.ai == before


def test_reference_prompt_is_abstract_and_product_locked():
    sc = _scene()
    assert product_ugc.apply_to_scene(
        sc,
        ctx=_ctx(["측면 버튼"]),
        identity=_Identity(),
        reference_prompt="Natural handheld close-up with a slow pan.",
    )

    prompt = sc.ai["prompt_override"]
    assert "REFERENCE-DERIVED STAGING ONLY" in prompt
    assert "Natural handheld close-up with a slow pan." in prompt
    assert "LOCKED ITEM: same navy body" in prompt
    assert "HAND/PRODUCT CONTACT" in prompt
    assert "CONTINUITY" in prompt
    assert "no generated spoken dialogue" in prompt
    assert sc.ai["settings"]["reference_pattern_only"] is True
    assert sc.ai["settings"]["product_fidelity_required"] is True
    assert sc.ai["settings"]["hand_contact_qa_required"] is True
    assert sc.ai["settings"]["reject_unverified_usage"] is True
    assert sc.ai["prompt_profile"] == "ai_product_ugc_v1"


def test_no_feature_blocks_invented_operation():
    sc = _scene(scene_type="DEMO")
    product_ugc.apply_to_scene(
        sc,
        ctx=_ctx([]),
        identity=_Identity(),
        reference_prompt="",
    )
    prompt = sc.ai["prompt_override"]
    assert "Do not press, turn, open, attach, remove, pour, apply, activate" in prompt
    assert "non-operational hold, rotate, point, or reveal action only" in prompt
    assert sc.ai["settings"]["reference_pattern_only"] is False


def test_feature_still_does_not_allow_unverified_mechanism():
    sc = _scene(scene_type="FEATURE")
    product_ugc.apply_to_scene(
        sc,
        ctx=_ctx(["컬러 LED 링"]),
        identity=_Identity(),
        reference_prompt="",
    )
    prompt = sc.ai["prompt_override"]
    assert "If the exact mechanism is not visually verified" in prompt
    assert "instead of inventing a button press" in prompt


def test_non_product_scene_is_ignored_without_ai_product_ugc():
    sc = SimpleNamespace(scene_type="HOOK", ai=None)
    assert not product_ugc.apply_to_scene(
        sc,
        ctx=_ctx(["측면 버튼"]),
        identity=_Identity(),
        reference_prompt="",
    )
