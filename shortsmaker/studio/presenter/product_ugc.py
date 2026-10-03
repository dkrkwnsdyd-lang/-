"""AI_PRODUCT_UGC prompt compiler.

This module is intentionally small and provider-agnostic.  It does not call a
video API.  It strengthens an AI_PRODUCT_UGC scene that has already been
planned by presenter.modes by combining:

1) the current product identity lock,
2) optional UGC reference-derived staging,
3) physically plausible hand/product interaction rules, and
4) visual-only output constraints.

Reference material is used only as an abstract staging/editing guide.  Creator
dialogue, branded sets, people, or exact shot sequences are never requested.
"""
from __future__ import annotations

from typing import Any


PROFILE = "ai_product_ugc_v1"

_PRODUCT_SCENES = {"DEMO", "FEATURE", "BENEFIT", "PRODUCT_REVEAL", "REVEAL"}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _scene_type(scene) -> str:
    return _text(getattr(scene, "scene_type", "") or getattr(scene, "beat", "")).upper()


def _features(ctx) -> list[str]:
    p = getattr(ctx, "p", None)
    return [str(x).strip() for x in (getattr(p, "features", None) or []) if str(x).strip()]


def _product_name(ctx) -> str:
    p = getattr(ctx, "p", None)
    return _text(getattr(p, "name", "")) or "the product"


def _identity_lock(identity) -> str:
    if identity is None:
        return ""
    fn = getattr(identity, "lock_prompt", None)
    if callable(fn):
        try:
            return _text(fn())
        except Exception:
            return ""
    return ""


def _interaction_rule(ctx, scene) -> str:
    """Return an interaction rule without inventing an unsupported operation."""
    kind = _scene_type(scene)
    feats = _features(ctx)
    if kind in ("DEMO", "FEATURE"):
        if feats:
            return (
                "Interaction: demonstrate only an operation or visible feature that is supported by "
                "the current product input/reference. If the exact mechanism is not visually verified, "
                "show it by holding, rotating, pointing to, or revealing the feature instead of inventing "
                "a button press, opening action, attachment, accessory, or mechanism."
            )
        return (
            "Interaction: no verified operating detail is available. Do not press, turn, open, attach, "
            "remove, pour, apply, activate, or otherwise invent a use. Use a non-operational hold, rotate, "
            "point, or reveal action only."
        )
    if kind in _PRODUCT_SCENES:
        return (
            "Interaction: keep the action simple and physically plausible; hold, present, rotate, or use "
            "the product only in a way visibly supported by the supplied reference/product information. "
            "Do not invent controls, accessories, mechanisms, effects, or results."
        )
    return (
        "Interaction: keep the product interaction minimal and factual. Do not invent a usage method, "
        "control, accessory, mechanism, effect, or result."
    )


def compose_prompt(*, base_prompt: str, ctx, scene, identity, reference_used: bool = False) -> str:
    """Compile the final visual prompt for one AI_PRODUCT_UGC scene."""
    name = _product_name(ctx)
    lock = _identity_lock(identity)
    prefix = (
        "REFERENCE-DERIVED STAGING ONLY: use the supplied staging/camera idea as an abstract UGC pattern, "
        "not as a copy. Do not reproduce any creator, face, dialogue, branded room, unique choreography, "
        "or exact shot sequence. "
        if reference_used
        else ""
    )
    base = _text(base_prompt)
    identity_rule = (
        f"CURRENT PRODUCT IDENTITY LOCK: {lock} "
        if lock
        else (
            f"CURRENT PRODUCT IDENTITY LOCK: keep '{name}' identical to the supplied product reference "
            "in shape, proportions, colors, printed marks, controls, and parts; do not redesign it. "
        )
    )
    hands = (
        "HAND/PRODUCT CONTACT: use a physically plausible grip and contact point. Hands must have natural "
        "anatomy and consistent scale; no fused, missing, duplicated, stretched, or extra fingers/hands. "
        "Fingers must not pass through the product. The product must not float, teleport, duplicate, melt, "
        "bend, morph, resize, or change orientation impossibly between frames. Do not add a second copy of "
        "the product. Keep identity-critical logo/printed text/buttons/parts visible whenever the shot is "
        "meant to identify or demonstrate them. "
    )
    continuity = (
        "CONTINUITY: the same exact product must persist from first frame to last frame with stable color, "
        "shape, logo/printed text, button/part positions, proportions, and material appearance. "
    )
    output = (
        "OUTPUT: authentic smartphone UGC visual, vertical 9:16, casual natural framing and lighting. "
        "Visual clip only: no generated spoken dialogue, no subtitles, no on-screen ad copy, no added "
        "brand marks, no price/rating/review/sales claims. Voice-over, captions, SFX, BGM, and CTA are added "
        "separately by SHOP SHORTS AI."
    )
    return " ".join(x for x in (prefix, base, identity_rule, _interaction_rule(ctx, scene), hands, continuity, output) if x)


def prompt_settings(*, reference_used: bool) -> dict:
    """Provider-agnostic metadata; providers may translate supported fields later."""
    return {
        "prompt_profile": PROFILE,
        "reference_pattern_only": bool(reference_used),
        "product_fidelity_required": True,
        "hand_contact_qa_required": True,
        "visual_only": True,
        "reject_unverified_usage": True,
    }


def apply_to_scene(scene, *, ctx, identity, reference_prompt: str = "") -> bool:
    """Attach a strengthened prompt only to AI_PRODUCT_UGC scenes.

    Returns True when the scene was changed.  AI_PRESENTER and other source
    types are deliberately ignored so reference UGC prompts cannot leak into
    presenter/talking-head scenes.
    """
    ai = getattr(scene, "ai", None)
    if not isinstance(ai, dict) or ai.get("kind") != "AI_PRODUCT_UGC":
        return False

    ref = _text(reference_prompt)
    base = ref or _text(ai.get("prompt"))
    ai["prompt_override"] = compose_prompt(
        base_prompt=base,
        ctx=ctx,
        scene=scene,
        identity=identity,
        reference_used=bool(ref),
    )
    settings = dict(ai.get("settings") or {})
    settings.update(prompt_settings(reference_used=bool(ref)))
    ai["settings"] = settings
    ai["prompt_profile"] = PROFILE
    return True
