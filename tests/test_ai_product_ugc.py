"""AI_PRODUCT_UGC prompt compiler regression tests.

These tests are intentionally provider-free: they verify prompt/routing safety without
making a paid video API call.
"""
from types import SimpleNamespace

from shortsmaker.studio.presenter import fidelity, product_ugc


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


class _VisionRouter:
    def __init__(self, value):
        self.value = value

    def has_real(self, task):
        return task == "vision"

    def run(self, *args, **kwargs):
        return SimpleNamespace(value=self.value)


def test_fidelity_rejects_bad_hand_contact(monkeypatch, tmp_path):
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"reference")
    monkeypatch.setattr(fidelity, "sample_frames", lambda clip, out_dir: ["frame1.jpg", "frame2.jpg"])
    router = _VisionRouter({
        "same_product": True,
        "fidelity": 96,
        "shape_changed": False,
        "color_changed": False,
        "logo_or_text_changed": False,
        "button_or_part_changed": False,
        "pattern_changed": False,
        "proportion_changed": False,
        "hand_anatomy_problem": True,
        "hand_product_intersection": False,
        "product_duplicate": False,
        "product_morph": False,
        "product_visible": True,
        "notes": "extra finger",
    })
    result = fidelity.check(router, str(ref), "clip.mp4", tmp_path / "qa")
    assert result["status"] == "PRODUCT_MISMATCH"
    assert "hand_anatomy_problem" in result["reasons"]


def test_fidelity_accepts_same_product_and_clean_interaction(monkeypatch, tmp_path):
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"reference")
    monkeypatch.setattr(fidelity, "sample_frames", lambda clip, out_dir: ["frame1.jpg", "frame2.jpg"])
    router = _VisionRouter({
        "same_product": True,
        "fidelity": 95,
        "shape_changed": False,
        "color_changed": False,
        "logo_or_text_changed": False,
        "button_or_part_changed": False,
        "pattern_changed": False,
        "proportion_changed": False,
        "hand_anatomy_problem": False,
        "hand_product_intersection": False,
        "product_duplicate": False,
        "product_morph": False,
        "product_visible": True,
        "notes": "clean",
    })
    result = fidelity.check(router, str(ref), "clip.mp4", tmp_path / "qa")
    assert result["status"] == "PASS"
