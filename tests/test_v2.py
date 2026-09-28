"""SHOP SHORTS V2 테스트 (외부 API 없이)."""
import json
from pathlib import Path

import pytest

from shortsmaker import brain
from shortsmaker.db import DB
from shortsmaker.providers import ModelEntry, Router, load_registry
from shortsmaker.providers.base import Provider, ProviderError, ProviderResult, Usage, mask, scrub
from shortsmaker.studio import compliance
from shortsmaker.studio.director import direct_scenes, rule_director
from shortsmaker.studio.editor import edit
from shortsmaker.studio.motion import split_caption
from shortsmaker.studio.product import ProductInput, analyze_photo, build_identity

from product_fixtures import PRODUCTS, make_photos


@pytest.fixture(scope="module")
def gun(tmp_path_factory):
    d = tmp_path_factory.mktemp("gun")
    photos = make_photos("fitness_massage_gun", d, 3)
    P = PRODUCTS["fitness_massage_gun"]
    p = ProductInput(name=P["name"], features=P["features"], problem=P["problem"], category_hint=P["category"],
                     photos=photos)
    identity = build_identity(p, [analyze_photo(x) for x in photos], "P-test")
    return p, identity


# ------------------------------------------------------------------ brain / registry
def test_brain_sections_load():
    for name in ["core_rules", "quality_rules", "hook_patterns", "story_patterns", "scene_rules", "camera_patterns",
                 "caption_rules", "tts_rules", "product_lock_rules", "rights_rules", "platform_rules",
                 "selling_angle_rules"]:
        assert brain.system(name)
    for pf in ["youtube", "instagram", "tiktok", "threads", "korea", "common"]:
        assert brain.policy(pf)
    assert len(brain.system("story_patterns")["patterns"]) == 10


def test_learned_knowledge_rejects_unverified(tmp_path):
    k = brain.LearnedKnowledge(tmp_path)
    assert not k.add("reference_patterns", {"status": "UNVERIFIED"})
    assert k.add("reference_patterns", {"status": "PARTIAL", "structure": {}})
    assert len(k.load("reference_patterns")) == 1


def test_registry_has_no_duplicate_priorities_per_task():
    reg = load_registry()
    seen = set()
    for m in reg:
        if m.enabled:
            key = (m.task, m.priority)
            assert key not in seen, key
            seen.add(key)


# ------------------------------------------------------------------ providers / router
class FakeLLM(Provider):
    name = "fake"

    def __init__(self, fail=False):
        super().__init__(api_key="sk-secretsecret123")
        self.fail = fail
        self.calls = 0

    def json(self, model, **kw):
        self.calls += 1
        if self.fail:
            raise ProviderError("boom sk-secretsecret123")
        return ProviderResult({"ok": model}, self.name, model, Usage(1000, 500))


def _router(tmp_path, provider, db=None):
    reg = [ModelEntry("fake", "llm", "m1", 1, True, 1, 3, ["json"], cost_per_1k_in=0.01, cost_per_1k_out=0.02),
           ModelEntry("local", "llm", "rule", 9, True, 0, 1, ["json"])]
    return Router(db=db, job_id="J", providers={"fake": provider}, registry=reg,
                  status_file=tmp_path / "st.json", sleep=lambda s: None)


def test_router_uses_provider_and_logs_cost(tmp_path):
    db = DB(tmp_path / "db.sqlite")
    r = _router(tmp_path, FakeLLM(), db)
    res = r.run("llm", "json", local_fn=lambda: "local", system="", user="")
    assert res.provider == "fake" and res.usage.estimated_cost == pytest.approx(0.02)
    assert db.job_cost("J") == pytest.approx(0.02)


def test_router_retries_then_falls_back_and_masks_keys(tmp_path):
    prov = FakeLLM(fail=True)
    r = _router(tmp_path, prov)
    res = r.run("llm", "json", local_fn=lambda: "local", system="", user="")
    assert res.provider == "local" and prov.calls == 2
    status = json.loads((tmp_path / "st.json").read_text())
    assert "secretsecret" not in status["fake"]["last_error"]


def test_mask_and_scrub():
    assert "secret" not in mask("sk-abcdefsecret99")
    assert "AIzaSyD" not in scrub("key=AIzaSyD1234567890abcdef")


def test_control_center_never_calls_paid_video(tmp_path):
    r = Router(status_file=tmp_path / "s.json")
    rows = {x["provider"]: x for x in r.control_center(test=True)}
    assert rows["seedance"]["status"] in ("not_configured", "configured_unverified")


# ------------------------------------------------------------------ db
def test_migration_up_down(tmp_path):
    db = DB(tmp_path / "x.db")
    assert db.applied() == ["0001_v2_init"]
    db.create_job("j1", "PRO", "p", {})
    assert db.rollback() == "0001_v2_init"
    assert db.applied() == []
    db.migrate()
    assert db.applied() == ["0001_v2_init"]


# ------------------------------------------------------------------ director
def test_rule_director_plan(gun):
    p, identity = gun
    plan = direct_scenes(rule_director(p, "PRO"), identity, p, "PRO")
    required = brain.system("scene_rules")["required_fields"]
    for s in plan.scenes:
        d = s.to_dict()
        assert all(k in d for k in required)
        assert s.reference_image in {ph["path"] for ph in identity.photos}
    assert plan.scenes[0].beat == "hook" and plan.scenes[-1].beat == "cta"
    assert plan.story_pattern == "PROBLEM_SOLUTION"
    assert 2.0 <= plan.reveal_at <= 4.0          # 제품을 0초에 무조건 노출하지 않음
    shots = [s.shot for s in plan.scenes]
    assert all(a != b for a, b in zip(shots, shots[1:]))   # 같은 구도 연속 금지
    lo, hi = plan.target_duration
    assert lo - 1 <= plan.duration <= hi + 2


def test_fast_mode_is_short(gun):
    p, identity = gun
    plan = direct_scenes(rule_director(p, "FAST"), identity, p, "FAST")
    assert len(plan.scenes) <= 5 and all(s.takes == 1 for s in plan.scenes)


def test_rule_director_never_invents_claims(gun):
    p, _ = gun
    text = json.dumps(rule_director(p, "PRO"), ensure_ascii=False)
    for bad in ["1위", "최고", "후기", "판매량", "특허", "인증", "완치", "100%"]:
        assert bad not in text


def test_photo_only_identity(tmp_path):
    photos = make_photos("beauty_serum", tmp_path, 1)
    p = ProductInput(photos=photos)
    ident = build_identity(p, [analyze_photo(x) for x in photos], "P")
    assert ident.name == "UNKNOWN" and ident.control_position == "UNKNOWN"
    assert "side" in ident.missing_angles


# ------------------------------------------------------------------ editor / captions
def test_split_caption_two_lines_and_emphasis():
    ws = split_caption("운동 끝나면 어깨가 뭉쳐요?\n아직도 [[참으세요]]?")
    assert max(w.line for w in ws) <= 1
    assert [w.text for w in ws if w.emphasis] == ["참으세요?"]


def test_editor_first_three_seconds(gun):
    p, identity = gun
    plan = direct_scenes(rule_director(p, "PRO"), identity, p, "PRO")
    edl = edit(plan, {})
    t = edl["timing"]
    assert 0.3 <= t["first_caption"] <= 0.7
    assert 0.8 <= t["first_visual_change"] <= 1.3
    assert 2.0 <= t["reveal_at"] <= 4.0
    assert t["max_shot"] <= brain.system("quality_rules")["pacing"]["max_shot_length"]
    assert any(e["sfx"] == "whoosh" for e in edl["events"])


# ------------------------------------------------------------------ compliance
def _gate(p, texts, copies=None, label=False, assets=None):
    copies = copies or {pf: {"caption": "hi"} for pf in compliance.PLATFORMS}
    return compliance.compliance_gate(p, texts, copies, label, assets or [{"path": "a", "rights": "OWNED"}])


def test_unknown_category_is_not_green():
    g = _gate(ProductInput(name="무언가"), {"s": "좋아요"})
    assert g["product"]["risk"] == "UNKNOWN"
    assert all(v["verdict"] == "UNKNOWN" for v in g["platforms"].values())


def test_red_category_blocked():
    g = _gate(ProductInput(name="전자담배 액상 세트", category_hint="생활"), {"s": "향이 좋아요"})
    assert all(v["verdict"] == "BLOCKED" for v in g["platforms"].values())


def test_claims_context_and_status():
    p = ProductInput(name="마사지건", category_hint="운동", claim_sources={"특허": "https://patent.example/123"})
    g = _gate(p, {"a": "통증 완화에 최고의 선택", "b": "특허 받은 헤드", "c": "치료 목적이 아닙니다"})
    by = {c["phrase"]: c["status"] for c in g["claims"]}
    assert by["통증 완화"] == "HIGH_RISK"
    assert by["최고의"] == "UNVERIFIED"
    assert by["특허"] == "SOURCE_BACKED"
    assert "치료" not in by                      # 부정 문맥
    assert all(v["verdict"] == "REQUIRES_EDIT" for v in g["platforms"].values())


def test_disclosure_required_for_affiliate():
    p = ProductInput(name="텀블러", category_hint="주방", affiliate="COUPANG_PARTNERS")
    g = _gate(p, {"s": "좋아요"}, label=False)
    assert g["disclosure"]["status"] == "REQUIRES_EDIT"
    text = brain.policy("korea")["disclosure_rules"]["COUPANG_PARTNERS"]
    ok = _gate(p, {"s": "좋아요"}, {pf: {"caption": text} for pf in compliance.PLATFORMS}, label=True)
    assert ok["disclosure"]["status"] == "PASS"
    assert all(v["verdict"] == "PASS" for v in ok["platforms"].values())


def test_reference_only_asset_blocks():
    g = _gate(ProductInput(name="텀블러", category_hint="주방"), {"s": "x"},
              assets=[{"path": "ref.mp4", "rights": "REFERENCE_ONLY"}])
    assert all(v["verdict"] == "BLOCKED" for v in g["platforms"].values())


# ------------------------------------------------------------------ platform copy
def test_platform_copies_are_different(gun):
    from shortsmaker.studio import adapter
    p, identity = gun
    p2 = ProductInput(**{**p.__dict__, "affiliate": "COUPANG_PARTNERS"})
    plan = direct_scenes(rule_director(p2, "PRO"), identity, p2, "PRO")
    copies = adapter.platform_copy(plan, p2)
    bodies = [copies["youtube"]["description"], copies["instagram"]["caption"], copies["tiktok"]["caption"],
              copies["threads"]["post"]]
    assert len(set(bodies)) == 4
    assert "#Shorts" in copies["youtube"]["title"] and len(copies["threads"]["post"]) <= 500
    assert all("쿠팡 파트너스" in b for b in bodies)


# ------------------------------------------------------------------ end-to-end (저해상도)
def test_pipeline_end_to_end_small(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 2)
    P = PRODUCTS["kitchen_tumbler"]
    r = run_job({"name": P["name"], "features": P["features"], "problem": P["problem"], "category_hint": "주방",
                 "photos": photos, "affiliate": "COUPANG_PARTNERS"}, "FAST", ["youtube", "threads"],
                out_root=tmp_path / "out", db=DB(tmp_path / "db.sqlite"), render=(270, 480, 10))
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL"), r.get("error")
    assert Path(r["master"]).exists()
    assert set(r["exports"]) == {"youtube", "threads"}
    assert r["compliance"]["disclosure"]["status"] == "PASS"
    assert all(e["file"] and Path(e["file"]).exists() for e in r["exports"].values())
    assert "overall" in r["qa"]["scores"]


def test_product_lock_rejects_unreliable_cutout(tmp_path):
    """흰 제품 + 밝은 배경: 배경 제거가 제품 일부를 지우므로 사용하지 않아야 한다."""
    from PIL import Image
    from shortsmaker.studio.product import cutout
    white = Image.open(make_photos("electronics_earbuds", tmp_path, 1)[0])
    dark = Image.open(make_photos("fitness_massage_gun", tmp_path, 1)[0])
    assert cutout(white) is None
    assert cutout(dark) is not None


def test_repair_targets_scene_and_respects_low_res(gun):
    from shortsmaker.studio.pipeline import _repair
    p, identity = gun
    plan = direct_scenes(rule_director(p, "PRO"), identity, p, "PRO")
    before = {s.scene_id: s.shot for s in plan.scenes}
    qa = {"failed": ["pacing", "visual_quality"],
          "repair_hints": {"repeat_scenes": ["S3"], "duration": None, "low_res": True, "monotone": False}}
    actions = _repair(plan, qa, identity)
    s3 = next(s for s in plan.scenes if s.scene_id == "S3")
    assert s3.shot not in ("macro", "detail_pan") and s3.shot != before["S3"]
    assert actions
    # 다시 돌려도 macro 로 되돌아가지 않음
    _repair(plan, qa, identity)
    assert s3.shot not in ("macro", "detail_pan")
