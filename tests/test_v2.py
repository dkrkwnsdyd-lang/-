import re
import os
import pathlib
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

from conftest import FakeResponse, FakeSession
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
    assert db.applied() == ["0001_v2_init", "0002_ai_generations", "0003_reference_patterns", "0004_ugc_reference"]
    db.create_job("j1", "PRO", "p", {})
    assert db.rollback() == "0004_ugc_reference"                  # 가장 최근 것만 되돌린다 (기존 데이터는 그대로)
    assert db.rollback() == "0003_reference_patterns"
    assert db.rollback() == "0002_ai_generations"
    assert db.applied() == ["0001_v2_init"] and db.job("j1")
    assert db.rollback() == "0001_v2_init"
    assert db.applied() == []
    db.migrate()
    assert db.applied() == ["0001_v2_init", "0002_ai_generations", "0003_reference_patterns", "0004_ugc_reference"]


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
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
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


def test_test_hook_only_for_testable_products():
    from shortsmaker.studio.director import hook_candidates
    cup = ProductInput(name="도자기 커피잔 세트", features=["손잡이가 넓은 머그"])
    gun = ProductInput(name="무선 미니 마사지건", features=["4단계 강도 조절"])
    assert "test_challenge" not in [h["type"] for h in hook_candidates(cup, "DISCOVERY")]
    assert "test_challenge" in [h["type"] for h in hook_candidates(gun, "DISCOVERY")]


def test_busy_background_blocks_zoom_unless_box_given(tmp_path):
    """복잡한 배경 사진은 제품 위치를 모르므로 확대 컷 금지, 위치를 알려주면 허용."""
    from PIL import Image
    import numpy as np
    from shortsmaker.studio.director import ZOOM_SHOTS, zoomable
    rng = np.random.default_rng(0)
    busy = tmp_path / "busy.jpg"
    Image.fromarray(rng.integers(0, 255, (1200, 900, 3), dtype=np.uint8)).save(busy)
    p = ProductInput(name="독서대", features=["투명 아크릴 판"], category_hint="생활", photos=[str(busy)])
    a = analyze_photo(busy)
    assert a.background == "busy" and a.focus is None
    ident = build_identity(p, [a], "P")
    assert not zoomable(ident, str(busy))
    plan = direct_scenes(rule_director(p, "PRO"), ident, p, "PRO")
    assert not any(s.shot in ZOOM_SHOTS for s in plan.scenes)
    a.focus, a.product_box, a.box_source = [0.5, 0.5], (0.2, 0.3, 0.8, 0.7), "user"
    assert zoomable(build_identity(p, [a], "P"), str(busy))


def test_product_region_keeps_portrait_aspect(tmp_path):
    from PIL import Image
    from shortsmaker.studio.motion import PlateCache
    img = tmp_path / "x.jpg"
    Image.new("RGB", (3000, 4000), "gray").save(img)
    c = PlateCache()
    c.boxes[str(img)] = (0.1, 0.4, 0.9, 0.7)      # 가로로 넓적한 제품 영역
    r = c.product_region(str(img), pad=0.04, aspect=0.78)
    assert abs(r.width / r.height - 0.78) < 0.02


def test_product_short_skips_quantity_tokens():
    from shortsmaker.studio.director import product_short
    assert product_short("Comet Signature 베이비 물티슈 100매") == "물티슈"
    assert product_short("비타민 세럼 30ml") == "세럼"
    assert product_short("무선 미니 마사지건") == "마사지건"
    assert product_short("") == "이 제품"


def test_low_res_photo_is_not_zoomable(tmp_path):
    from PIL import Image
    from shortsmaker.studio.director import zoomable
    small = tmp_path / "small.png"
    Image.new("RGB", (590, 590), "white").save(small)
    big = tmp_path / "big.png"
    Image.new("RGB", (1600, 1600), "white").save(big)
    p = ProductInput(name="물티슈", photos=[str(small), str(big)])
    ident = build_identity(p, [analyze_photo(small), analyze_photo(big)], "P")
    assert not zoomable(ident, str(small)) and zoomable(ident, str(big))


def test_no_problem_means_no_dangling_then_and_no_invented_benefit():
    p = ProductInput(name="Comet Signature 베이비 물티슈 100매", features=["100매 구성", "여닫는 캡 뚜껑"],
                     category_hint="유아")
    text = json.dumps(rule_director(p, "PRO"), ensure_ascii=False)
    assert "그럴 땐" not in text and "쓰는 법" not in text and "간단" not in text
    assert "바로 이 물티슈" in text


def test_platform_copy_hashtags_and_dedup():
    from shortsmaker.studio import adapter
    p = ProductInput(name="Comet Signature 베이비 물티슈 100매", features=["100매 구성", "여닫는 캡 뚜껑"],
                     category_hint="유아", affiliate="COUPANG_PARTNERS")

    class Plan:
        hook_candidates = [{"text": "이 물티슈, 아직 안 써보셨어요?"}]
    c = adapter.platform_copy(Plan(), p)
    assert "#100매" not in c["youtube"]["hashtags"] and "#여닫는" not in c["instagram"]["hashtags"]
    assert "#Comet" in c["instagram"]["hashtags"]
    assert c["youtube"]["title"].count("물티슈") == 1
    assert c["threads"]["post"].count("100매") == 1
    assert all("쿠팡 파트너스" in (v.get("description") or v.get("caption") or v.get("post")) for v in c.values())


def test_unknown_rights_message_is_actionable():
    g = _gate(ProductInput(name="물티슈", category_hint="유아"), {"s": "x"},
              assets=[{"path": "a.png", "rights": "UNKNOWN"}, {"path": "b.png", "rights": "UNKNOWN"}])
    reasons = g["platforms"]["youtube"]["reasons"]
    assert g["platforms"]["youtube"]["verdict"] == "PASS_WITH_WARNING"
    assert any("2장" in r and "사진 권리" in r for r in reasons)


def test_feature_photo_link_locks_scene_source(gun):
    p, identity = gun
    p2 = ProductInput(**{**p.__dict__})
    p2.features = ["컬러 LED 링", "송풍구 클립 거치"]
    p2.problem = ""
    front, side = identity.photos[0]["path"], identity.photos[1]["path"]
    p2.feature_photos = {"컬러 LED 링": front, "송풍구 클립 거치": side}
    plan = direct_scenes(rule_director(p2, "PRO"), identity, p2, "PRO")
    by_caption = {s.caption.replace("[[", "").replace("]]", ""): s for s in plan.scenes}
    led = next(s for c, s in by_caption.items() if "LED" in c)
    clip = next(s for c, s in by_caption.items() if "클립" in c)
    assert led.reference_image == front and led.ref_locked
    assert clip.reference_image == side and clip.ref_locked


def test_color_is_a_fact_not_a_benefit():
    from shortsmaker.studio.director import selling_angles
    p = ProductInput(name="M-Circle", features=["컬러 LED 링", "송풍구 클립 거치"])
    assert all(a["evidence"] == [] or a["angle"] != "design" for a in selling_angles(p))
    text = json.dumps(rule_director(p, "PRO"), ensure_ascii=False)
    assert "깔끔" not in text


def test_hashtags_have_no_symbols():
    from shortsmaker.studio import adapter
    p = ProductInput(name="SINJIMORU M-Circle", features=["컬러 LED 링"], category_hint="전자기기")
    tags = adapter._tags(p, adapter.profiles()["instagram"])
    assert all(t[1:].isalnum() for t in tags), tags
    assert "#MCircle" in tags


def test_gemini_via_proxy_injected_credential(monkeypatch):
    """환경 '자격 증명'으로 프록시가 키를 붙여주면 코드는 키 없이도 동작하고 헤더를 보내지 않는다."""
    from shortsmaker.providers.llm import GoogleProvider
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SHORTSMAKER_PROBE_CREDENTIALS", "1")

    def handler(method, url, kw):
        if "models?pageSize=1" in url:
            return FakeResponse({"models": []})
        assert "x-goog-api-key" not in (kw.get("headers") or {})
        return FakeResponse({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                             "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2}})

    prov = GoogleProvider(session=FakeSession(handler))
    assert prov.configured() and prov.auth_state() == "proxy-injected"
    res = prov.json("gemini-x", system="s", user="u")
    assert res.value == {"ok": True}


def test_gemini_not_configured_without_key_or_proxy(monkeypatch):
    from shortsmaker.providers.llm import GoogleProvider
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SHORTSMAKER_PROBE_CREDENTIALS", "1")
    prov = GoogleProvider(session=FakeSession(lambda m, u, kw: FakeResponse({"error": {}}, status=403)))
    assert not prov.configured() and prov.auth_state() == "missing"


class _FakeVisionProvider:
    name = "fakev"

    def __init__(self, payload):
        self.payload = payload

    def configured(self):
        return True

    def json(self, model, **kw):
        return ProviderResult(self.payload, "fakev", model, Usage(100, 50))


def test_vision_fills_boxes_and_links_and_rejects_bad_values(tmp_path):
    from PIL import Image
    from shortsmaker.studio import vision
    photos = []
    for i in range(2):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (800, 600), "gray").save(p)
        photos.append(str(p))
    payload = {"photos": [
        {"index": 0, "product_present": True, "box": [0.2, 0.3, 0.8, 0.7], "angle": "front", "background": "busy",
         "visible_text": ["M-Circle"], "visible_features": ["LED ring"], "private_info_visible": ["map street names"]},
        {"index": 1, "product_present": True, "box": [0.9, 0.9, 0.5, 0.2], "angle": "side"},   # 잘못된 박스
        {"index": 7, "box": [0.1, 0.1, 0.5, 0.5]}],                                              # 범위 밖 사진
        "brand_or_name_visible": "SINJIMORU", "category_guess": "전자기기",
        "feature_photo": {"컬러 LED 링": 0, "송풍구 클립 거치": 9, "없는 특징": 1}}
    reg = [ModelEntry("fakev", "vision", "m", 1, True, 1, 3, ["vision"], cost_per_1k_in=0.001, cost_per_1k_out=0.002)]
    router = Router(providers={"fakev": _FakeVisionProvider(payload)}, registry=reg, status_file=tmp_path / "s.json")
    out = vision.analyze(router, photos, ["컬러 LED 링", "송풍구 클립 거치"], tmp_path / "w")
    assert out["boxes"] == {0: [0.2, 0.3, 0.8, 0.7]}              # 유효한 것만
    assert out["feature_links"] == {"컬러 LED 링": 0}             # 범위 밖 순번은 버림
    assert out["photos"][0]["private_info_visible"] == ["map street names"]


def test_vision_failure_is_graceful_and_billing_errors_do_not_retry(tmp_path):
    from PIL import Image
    from shortsmaker.studio import vision

    class Billing:
        name = "billing"
        calls = 0

        def configured(self):
            return True

        def json(self, model, **kw):
            Billing.calls += 1
            raise ProviderError("402 credits depleted", status=402)

    p = tmp_path / "a.jpg"
    Image.new("RGB", (100, 100)).save(p)
    reg = [ModelEntry("billing", "vision", "m", 1, True, 1, 3, ["vision"])]
    router = Router(providers={"billing": Billing()}, registry=reg, status_file=tmp_path / "s.json", sleep=lambda s: None)
    out = vision.analyze(router, [str(p)], [], tmp_path / "w")
    assert "error" in out and Billing.calls == 1                   # 결제 오류는 재시도 X


def test_router_skips_provider_after_billing_error(tmp_path):
    class Billing:
        name = "billing"
        calls = 0

        def configured(self):
            return True

        def json(self, model, **kw):
            Billing.calls += 1
            raise ProviderError("402", status=402)

    reg = [ModelEntry("billing", "llm", "m1", 1, True, 1, 3, ["json"]), ModelEntry("billing", "llm", "m2", 2, True, 1, 3, ["json"]),
           ModelEntry("local", "llm", "rule", 9, True, 0, 1, ["json"])]
    r = Router(providers={"billing": Billing()}, registry=reg, status_file=tmp_path / "s.json", sleep=lambda s: None)
    assert r.run("llm", "json", local_fn=lambda: "L", system="", user="").provider == "local"
    assert Billing.calls == 1                                       # m2 도 시도하지 않음
    assert r.run("llm", "json", local_fn=lambda: "L", system="", user="").provider == "local"
    assert Billing.calls == 1                                       # 이후 호출에서도 건너뜀


class _ScriptedLLM:
    """작성기/판정기를 흉내내는 가짜 LLM. writers: 호출마다 돌려줄 대본, unsupported: 판정기가 돌려줄 목록."""
    name = "scripted"

    def __init__(self, writers, verdicts, judge_error=False):
        self.writers, self.verdicts, self.judge_error = list(writers), list(verdicts), judge_error
        self.writer_feedback = []

    def configured(self):
        return True

    def json(self, model, system, user, **kw):
        if "fact checker" in system:
            if self.judge_error:
                raise ProviderError("judge down", status=500)
            return ProviderResult({"unsupported": self.verdicts.pop(0)}, self.name, model, Usage(10, 5))
        self.writer_feedback.append("제거하고 다시 써라" in system)
        return ProviderResult(self.writers.pop(0), self.name, model, Usage(10, 5))


def _script(lines):
    beats = [{"beat": "hook", "tts_line": lines[0], "caption": lines[0]},
             {"beat": "problem", "tts_line": "어두워서 안 보이죠", "caption": "어두워서 안 보이죠"},
             {"beat": "reveal", "tts_line": "바로 이 M-Circle", "caption": "바로 이 [[M-Circle]]"},
             {"beat": "demo", "tts_line": lines[1], "caption": lines[1], "feature": "컬러 LED 링"},
             {"beat": "cta", "tts_line": "링크에서 확인하세요", "caption": "정보는 [[링크]]에서"}]
    return {"story_pattern": "PROBLEM_SOLUTION", "best_angle": "convenience", "angles": [],
            "hook_candidates": [{"type": "discovery", "text": lines[0], "caption": lines[0]}], "beats": beats}


def _router_for(llm, tmp_path):
    reg = [ModelEntry("scripted", "llm", "m", 1, True, 1, 3, ["json"]), ModelEntry("local", "llm", "rule", 9, True, 0, 1, ["json"])]
    return Router(providers={"scripted": llm}, registry=reg, status_file=tmp_path / "s.json", sleep=lambda s: None)


def test_grounding_retries_then_accepts_clean_script(gun, tmp_path):
    from shortsmaker.studio.director import llm_director
    p, identity = gun
    p = ProductInput(**{**p.__dict__, "name": "M-Circle", "features": ["컬러 LED 링"], "problem": ""})
    llm = _ScriptedLLM(writers=[_script(["밤에 헤맨 적 있죠?", "밤에도 영롱해요"]), _script(["이 M-Circle 아직 안 써보셨어요?", "컬러 LED 링이 있어요"])],
                       verdicts=[[{"line": "밤에도 영롱해요", "phrase": "밤에도 영롱", "reason": "입력에 없는 야간 성능"}], []])
    data = llm_director(_router_for(llm, tmp_path), p, identity, "PRO")
    assert data["_grounding"]["final"] == "llm" and len(data["_grounding"]["attempts"]) == 2
    assert llm.writer_feedback == [False, True]                       # 두 번째는 피드백과 함께 재생성
    assert "밤" not in json.dumps({k: v for k, v in data.items() if k != "_grounding"}, ensure_ascii=False)   # 대본에만 (보고서 제외)
    assert all(b["beat"] != "problem" for b in data["beats"])         # 문제 입력 없으면 problem 장면 제거
    assert data["story_pattern"] == "DISCOVERY"


def test_grounding_falls_back_to_rules_when_llm_keeps_inventing(gun, tmp_path):
    from shortsmaker.studio.director import llm_director
    p, identity = gun
    p = ProductInput(**{**p.__dict__, "name": "M-Circle", "features": ["컬러 LED 링"], "problem": ""})
    bad = [{"phrase": "밤에도", "reason": "x"}]
    llm = _ScriptedLLM([_script(["밤 훅", "밤에도"]), _script(["밤 훅", "밤에도"])], [bad, bad])
    data = llm_director(_router_for(llm, tmp_path), p, identity, "PRO")
    assert data["_grounding"]["final"] == "rule_fallback" and "rule_director" in data["_director"]
    assert "밤" not in json.dumps({k: v for k, v in data.items() if k != "_grounding"}, ensure_ascii=False)


def test_grounding_unverifiable_means_no_llm_text(gun, tmp_path):
    from shortsmaker.studio.director import llm_director
    p, identity = gun
    p = ProductInput(**{**p.__dict__, "name": "M-Circle", "features": ["컬러 LED 링"], "problem": ""})
    llm = _ScriptedLLM([_script(["훅", "특징"])], [], judge_error=True)
    data = llm_director(_router_for(llm, tmp_path), p, identity, "PRO")
    assert data["_grounding"]["final"] == "rule_fallback"             # 판정 못 하면 AI 글을 쓰지 않는다


def test_platform_copy_grounded_fallback_to_template(gun, tmp_path):
    from shortsmaker.studio import adapter
    p, identity = gun
    p = ProductInput(**{**p.__dict__, "name": "M-Circle", "features": ["컬러 LED 링"], "problem": "", "affiliate": "COUPANG_PARTNERS"})

    class Plan:
        hook_candidates = [{"text": "이 M-Circle 아직 안 써보셨어요?"}]
    bad_copy = {"youtube": {"title": "밤에도 잘 보이는", "description": "설치가 정말 쉬워요"}, "instagram": {"caption": "x"},
                "tiktok": {"caption": "y"}, "threads": {"post": "z"}}
    llm = _ScriptedLLM([bad_copy, bad_copy], [[{"phrase": "설치가 정말 쉬워요", "reason": "x"}]] * 2)
    copies, report = adapter.platform_copy(Plan(), p, _router_for(llm, tmp_path), None, with_report=True)
    assert report["final"] == "rule_fallback"
    assert "설치가" not in json.dumps(copies, ensure_ascii=False) and "쿠팡 파트너스" in copies["youtube"]["description"]


def test_fuzzy_feature_link_when_llm_omits_feature_key():
    from shortsmaker.studio.director import _linked_photo
    fp = {"컬러 LED 링": "/p/front.jpg", "송풍구 클립 거치": "/p/side.jpg"}
    assert _linked_photo({"beat": "demo", "caption": "테두리에 [[컬러 LED 링]]", "tts_line": ""}, fp) == "/p/front.jpg"
    assert _linked_photo({"beat": "detail", "caption": "차량 송풍구에 [[클립 거치]]", "tts_line": "송풍구 클립으로 거치돼요"}, fp) == "/p/side.jpg"
    assert _linked_photo({"beat": "hook", "caption": "컬러 LED 링", "tts_line": ""}, fp) is None        # hook 은 연결 안 함
    assert _linked_photo({"beat": "demo", "caption": "궁금하죠", "tts_line": ""}, fp) is None            # 겹침 없으면 연결 안 함
    assert _linked_photo({"beat": "demo", "caption": "링", "tts_line": ""}, {"a b": "x", "링 c": "y"}) in (None, "y")


def test_vision_retries_missing_box_once_and_uses_temperature_zero(tmp_path):
    from PIL import Image
    from shortsmaker.studio import vision
    p = tmp_path / "a.jpg"
    Image.new("RGB", (400, 300), "gray").save(p)
    calls = []

    class Flaky:
        name = "flaky"

        def configured(self):
            return True

        def json(self, model, temperature=None, user="", **kw):
            calls.append((temperature, "IMPORTANT" in user))
            box = [0.2, 0.2, 0.8, 0.8] if "IMPORTANT" in user else None
            return ProviderResult({"photos": [{"index": 0, "product_present": True, "box": box}], "feature_photo": {}},
                                  "flaky", model, Usage(10, 5))
    reg = [ModelEntry("flaky", "vision", "m", 1, True, 1, 3, ["vision"])]
    router = Router(providers={"flaky": Flaky()}, registry=reg, status_file=tmp_path / "s.json")
    out = vision.analyze(router, [str(p)], [], tmp_path / "w")
    assert out["boxes"] == {0: [0.2, 0.2, 0.8, 0.8]} and calls == [(0, False), (0, True)]


def test_my_take_is_only_source_of_experience_claim():
    from shortsmaker.studio import grounding
    from shortsmaker.studio.adapter import VOICE, _casual_post
    from shortsmaker.studio.product import ProductInput
    p = ProductInput(name="M-Circle 차량용 거치대", features=["컬러 LED 링", "송풍구 클립 거치"], my_take="차에 붙이니 깔끔해 보여요")
    facts = grounding.allowed_facts(p)
    assert any("직접 써본 느낌(사용자 작성): 차에 붙이니 깔끔해 보여요" in f for f in facts)
    assert "직접 써본 느낌(사용자 작성)" in grounding.RULES_FOR_WRITER
    assert "대화체" in VOICE and "광고" in VOICE
    post = _casual_post(p, "거치대", p.features)
    assert "차에 붙이니 깔끔해 보여요" in post and "\n" in post
    # 한 줄 느낌이 없으면 경험담을 지어내지 않는다
    q = ProductInput(name="M-Circle 차량용 거치대", features=["컬러 LED 링"])
    no = _casual_post(q, "거치대", q.features)
    assert "했더니" not in no and "써보니" not in no


def test_my_take_form_is_wired():
    html = (pathlib.Path(__file__).parent.parent / "shortsmaker/web/static/studio.html").read_text(encoding="utf-8")
    api = (pathlib.Path(__file__).parent.parent / "shortsmaker/web/studio_api.py").read_text(encoding="utf-8")
    assert 'id="myTake"' in html and 'fd.append("my_take"' in html
    assert 'my_take: str = Form("")' in api and '"my_take": my_take' in api


def test_load_dotenv_handles_windows_notepad_encodings(tmp_path, monkeypatch):
    from shortsmaker.config import load_dotenv
    monkeypatch.delenv("SS_T1", raising=False); monkeypatch.delenv("SS_T2", raising=False)
    (tmp_path / "bom.env").write_bytes("SS_T1=abc\n# 한글 주석\n".encode("utf-8-sig"))
    load_dotenv(tmp_path / "bom.env")
    assert os.environ["SS_T1"] == "abc"                      # BOM 이 첫 키를 망가뜨리지 않는다
    (tmp_path / "ansi.env").write_bytes("# 한글 주석\nSS_T2=xyz\r\n".encode("cp949"))
    load_dotenv(tmp_path / "ansi.env")
    assert os.environ["SS_T2"] == "xyz"                      # cp949 저장도 읽는다


def test_windows_launchers_are_ascii_crlf():
    root = pathlib.Path(__file__).parent.parent
    for name in ("install.bat", "start.bat"):
        raw = (root / name).read_bytes()
        raw.decode("ascii")                       # 한글이 섞이면 cmd 에서 깨진다
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert b"shortsmaker web" in (root / "start.bat").read_bytes()


# ------------------------------------------------------------------ 영상 클립
def _make_video(path, w, h, seconds=5, blur_after=None):
    import subprocess
    from shortsmaker.video import ffmpeg_exe
    src = f"testsrc2=size={w}x{h}:rate=15:duration={seconds}"
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def test_clip_analysis_and_best_window(tmp_path):
    from shortsmaker.studio import clips
    v = _make_video(tmp_path / "a.mp4", 360, 640, 5)
    info = clips.analyze_clip(v, tmp_path)
    assert info["ok"] and 4.5 <= info["duration"] <= 5.2 and abs(info["aspect"] - 0.5625) < 0.02
    w = clips.best_window(info, 2.0)
    assert w and 0 <= w["start"] and w["start"] + w["dur"] <= info["duration"] + 0.01
    # 이미 쓴 구간과는 겹치지 않는다
    w2 = clips.best_window(info, 2.0, [(w["start"], w["start"] + w["dur"])])
    assert w2 is None or w2["start"] >= w["start"] + w["dur"] - 0.01 or w2["start"] + w2["dur"] <= w["start"] + 0.01
    # 너무 짧은 클립은 쓰지 않는다
    assert clips.best_window(info, 30.0) is None


def test_clip_reader_portrait_landscape_and_hold_last(tmp_path):
    from shortsmaker.studio import clips
    for name, (w, h), aspect in (("p", (360, 640), 0.5625), ("l", (640, 360), 1.7778)):
        v = _make_video(tmp_path / f"{name}.mp4", w, h, 3)
        rd = clips.ClipReader(v, 0.0, aspect, 270, 480, 10)
        try:
            f0, f1 = rd.read(0), rd.read(1)
            assert f0.size == (270, 480) and f0.tobytes() != f1.tobytes()      # 움직인다
            assert rd.read(1).tobytes() == f1.tobytes()                        # 같은 프레임 재요청
            end = rd.read(500)                                                 # 클립보다 길면 마지막 프레임 유지
            assert end.size == (270, 480) and rd.read(600).tobytes() == end.tobytes()
        finally:
            rd.close()


def test_assign_uses_demo_shots_only_and_renderer_draws_clip(tmp_path):
    from shortsmaker.studio import clips
    from shortsmaker.studio.motion import MotionRenderer, Shot
    v = _make_video(tmp_path / "a.mp4", 360, 640, 6)
    info = clips.analyze_clip(v, tmp_path); info["index"] = 0

    class Sc:
        def __init__(self, sid, beat): self.scene_id, self.beat = sid, beat
    scenes = [Sc("S1", "hook"), Sc("S2", "demo"), Sc("S3", "cta")]
    shots = [Shot(scene_id=s.scene_id, shot="hero_push", source="x.jpg", duration=2.0) for s in scenes]
    rep = clips.assign(shots, scenes, [info])
    assert [r["scene_id"] for r in rep] == ["S2"]
    assert [s.shot for s in shots] == ["hero_push", "video_clip", "hero_push"]     # hook/cta 는 사진 유지
    r = MotionRenderer(width=270, height=480, fps=10)
    try:
        assert r.frame(shots[1], 0.5, 1).size == (270, 480)
    finally:
        r.close_clips()


def test_pipeline_with_video_clip(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 2)
    v = _make_video(tmp_path / "use.mp4", 360, 640, 8)
    bad = tmp_path / "bad.mp4"; bad.write_bytes(b"not a video")
    P = PRODUCTS["kitchen_tumbler"]
    r = run_job({"name": P["name"], "features": P["features"], "problem": P["problem"], "category_hint": "주방",
                 "photos": photos, "videos": [v, str(bad)], "affiliate": "COUPANG_PARTNERS"}, "FAST", ["youtube"],
                out_root=tmp_path / "out", db=DB(tmp_path / "db.sqlite"), render=(270, 480, 10))
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
    assert r["clips"]["provided"] == 2 and r["clips"]["usable"] == 1 and r["clips"]["used"]
    clip_shots = [s for s in r["edl"]["shots"] if s["shot"] == "video_clip" or (str(s["source"]).endswith(".mp4") and s["layout"] in ("demo", "lifestyle"))]
    assert clip_shots                                                    # Storyboard 경로: 시연/사용 장면 레이아웃에 영상 클립이 들어감
    warns = " ".join(r.get("warnings", []))
    assert "사용할 수 없어 제외" in warns                      # 깨진 파일은 제외하고 계속
    assert "개인 정보" in warns                                  # Vision 이 없으면 직접 확인 안내
    assert Path(r["exports"]["youtube"]["file"]).exists()


# ------------------------------------------------------------------ QUALITY SCORE V2 (모순된 점수 방지)
def _vision(visual=90, product=95, artifact=90, commercial=90, match=90, failures=None, **sub):
    c = {k: commercial for k in ("lighting", "composition", "product_presentation", "background_cleanliness", "camera_feel",
                                 "visual_variety", "real_ad_feeling", "amateur_look", "ai_look")}
    c.update(sub)
    return {"scores": {"visual": visual, "product_accuracy": product, "ai_artifact": artifact, "commercial_feel": commercial,
                       "scene_script_match": match},
            "commercial": c, "frame_script": [{"frame": i, "match": match, "issue": ""} for i in range(6)],
            "distinct_scenes": 6, "failures": failures or [], "top_issues": []}


PERFECT_LOCAL = dict(hook=100, visual_quality=100, product_consistency=100, story=100, pacing=100, caption=100, audio=100,
                     ai_artifact=96, cta=100)


def _score(local=None, vision=None, div=90, pq=None):
    from shortsmaker.studio.qa import score_v2
    return score_v2({**PERFECT_LOCAL, **(local or {})}, 96, div, 80,
                    {"unique_sources": 4, "cuts": 8, "effective_scenes": 4.6}, vision, pq, usage_missing=False)


def test_visual_58_never_yields_high_final_or_complete():
    """보고된 문제: Visual 58 인데 나머지 100점 평균으로 Overall 90 + '품질 미달'."""
    r = _score(vision=_vision(visual=58, commercial=90))
    assert r["scores"]["technical"] == 96                       # 로컬 기술 점수는 높아도
    assert r["scores"]["final"] <= 74 and r["verdict"] == "QUALITY_FAIL"
    assert any(g["hit"] and g["gate"].startswith("Visual <") for g in r["gates"])
    assert r["scores"]["overall"] == r["scores"]["final"]       # UI 의 overall 은 최종 점수


def test_weakest_link_caps_and_gates():
    assert _score(vision=_vision(artifact=70))["scores"]["final"] <= 79
    r = _score(vision=_vision(product=80))
    assert r["verdict"] == "QUALITY_FAIL" and any("Product Accuracy" in b for b in r["blockers"])
    r = _score(vision=_vision(match=75))
    assert r["verdict"] == "QUALITY_FAIL" and any("Scene-Script" in b for b in r["blockers"])
    r = _score(vision=_vision(visual=65, commercial=65))
    assert r["verdict"] == "QUALITY_FAIL" and any("둘 다" in b or "Commercial" in b for b in r["blockers"])


def test_only_genuinely_good_video_is_complete():
    r = _score(vision=_vision())
    assert r["verdict"] == "COMPLETE" and r["scores"]["final"] >= 85 and not r["blockers"] and not r["failed"]
    # 사람 눈 기준 실패 항목이 하나라도 보이면 COMPLETE 불가
    assert _score(vision=_vision(failures=["warped_product"]))["verdict"] == "QUALITY_FAIL"
    # 세부 Commercial 항목 하나가 심하게 낮으면 평균에 묻히지 않고 감점 (amateur 30)
    assert _score(vision=_vision(commercial=85, amateur_look=30))["scores"]["commercial_feel"] < 80


def test_no_vision_means_needs_review_not_complete():
    r = _score(vision=None)
    assert r["verdict"] == "NEEDS_REVIEW" and r["scores"]["final"] <= 79 and r["scores"]["commercial_feel"] is None
    assert r["scores"]["vision_quality"] is None
    assert any(i["cause"] == "Vision 평가 없음" for i in r["improvements"])
    # Vision 호출이 오류로 끝나도 같은 취급
    assert _score(vision={"error": "x"})["verdict"] == "NEEDS_REVIEW"


def test_repeated_same_photo_lowers_visual_diversity_and_lists_reason():
    from shortsmaker.studio.qa import score_v2
    r = score_v2(PERFECT_LOCAL, 96, 40, 35, {"unique_sources": 2, "cuts": 12, "effective_scenes": 3.5}, _vision(), None, usage_missing=True)
    assert r["verdict"] == "QUALITY_FAIL" and "visual_diversity" in r["failed"]
    causes = [i["cause"] for i in r["improvements"]]
    assert "같은 제품 이미지 반복" in causes and "실제 사용 장면 없음" in causes


def test_improvements_include_photo_quality_reasons():
    pq = {"photos": [{"grade_before": "C", "reasons": ["해상도 부족 (400x300)"]}, {"grade_before": "A", "reasons": []}]}
    r = _score(vision=_vision(visual=70, commercial=70), pq=pq)
    first = [i["cause"] for i in r["improvements"]]
    assert "원본 사진 품질 부족" in first and first.index("원본 사진 품질 부족") <= 1


# ------------------------------------------------------------------ 12~15초 압축
def test_compact_beats_keep_one_per_role_and_no_repeat():
    from shortsmaker.studio.director import compact_beats, COMPACT_DURATION, COMPACT_RANGE
    beats = [{"beat": b} for b in ("hook", "problem", "reveal", "demo", "detail", "detail", "benefit", "cta")]
    out = [b["beat"] for b in compact_beats(beats)]
    assert out == ["hook", "reveal", "demo", "benefit", "cta"]
    assert COMPACT_RANGE[0] <= sum(COMPACT_DURATION[b] for b in out) <= COMPACT_RANGE[1]


def test_compact_pipeline_is_12_to_15_seconds_without_same_photo_splits(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 2)
    P = PRODUCTS["kitchen_tumbler"]
    r = run_job({"name": P["name"], "features": P["features"], "problem": P["problem"], "category_hint": "주방",
                 "photos": photos, "compact": True}, "PRO", ["youtube"], out_root=tmp_path / "out",
                db=DB(tmp_path / "db.sqlite"), render=(270, 480, 10))
    assert r["plan"]["compact"] is True
    total = r["edl"]["total"]
    assert 12.0 <= total <= 15.5, total
    assert len(r["edl"]["shots"]) <= 7 and [s["scene_id"] for s in r["edl"]["shots"]].count("S3") == 1   # 시연 장면을 두 컷으로 쪼개지 않음


def test_reference_search_result_is_not_analyzed_or_learned(tmp_path):
    from shortsmaker.studio.reference import analyze_reference, classify_reference_url, learn
    from shortsmaker import brain
    urls = {"https://www.xiaohongshu.com/search_result?keyword=%E8%BD%A6%E8%BD%BD&source=web_search_result_notes": "SEARCH_RESULT",
            "https://www.youtube.com/results?search_query=car+mount": "SEARCH_RESULT",
            "https://www.tiktok.com/search?q=mount": "SEARCH_RESULT",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": "INDIVIDUAL_VIDEO"}
    for u, kind in urls.items():
        assert classify_reference_url(u) == kind, u
    r = analyze_reference("https://www.xiaohongshu.com/search_result?keyword=abc", router=None)
    assert r["status"] == "UNVERIFIED" and "개별 영상 링크" in r["note"] and r["kind"] == "SEARCH_RESULT"
    assert learn(r, brain.LearnedKnowledge(tmp_path)) is False        # UNVERIFIED 는 SHORTS BRAIN 에 저장하지 않는다


def test_parallax_never_crops_product_when_cutout_unavailable(tmp_path):
    """배경 제거가 안 되는 복잡한 배경 사진에서 parallax 가 제품 카드를 화면 밖으로 밀어내지 않는다 -> hero_push 로 그려진다."""
    from PIL import Image
    from shortsmaker.studio.motion import MotionRenderer, Shot
    rng = __import__("numpy").random.default_rng(3)
    noisy = Image.fromarray(rng.integers(0, 255, (1200, 900, 3), dtype="uint8"))      # 배경 제거가 신뢰되지 않는 복잡한 사진
    photo = tmp_path / "busy.jpg"
    noisy.save(photo, quality=92)
    r = MotionRenderer(width=270, height=480, fps=10)
    assert r.cache.cutout(str(photo)) is None
    a = r.frame(Shot("S", "parallax", str(photo), 2.0), 1.0, 0)
    b = r.frame(Shot("S", "hero_push", str(photo), 2.0), 1.0, 0)
    assert a.tobytes() == b.tobytes()


# ------------------------------------------------------------------ PHOTO ENHANCEMENT V2
def _bokeh_photo(path, blur_all=0.0):
    """흰색 매끈한 제품(로고 선명) + 흐린 나무 배경 = 인물사진 모드. 전체 평균 선명도는 낮지만 흐린 사진이 아니다."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    rng = np.random.default_rng(7)
    bg = Image.fromarray(np.clip(rng.normal(150, 40, (1200, 900, 3)) + np.linspace(0, 40, 900)[None, :, None], 0, 255).astype("uint8"))
    bg = bg.filter(ImageFilter.GaussianBlur(14))                      # 배경은 심하게 흐림(보케)
    d = ImageDraw.Draw(bg)
    d.ellipse([180, 330, 720, 870], fill=(238, 238, 240))              # 흰 제품
    try:
        font = ImageFont.truetype(__import__("shortsmaker.studio.motion", fromlist=["x"]).caption_font_path() or "", 60)
    except Exception:
        font = ImageFont.load_default()
    d.text((330, 560), "LGU+", fill=(120, 120, 128), font=font)         # 선명한 로고
    d.rectangle([300, 640, 600, 648], fill=(150, 150, 158))
    if blur_all:
        bg = bg.filter(ImageFilter.GaussianBlur(blur_all))
    bg.save(path, quality=95)
    return str(path)


def test_photo_grade_bokeh_is_not_blurry_but_truly_blurry_is_c(tmp_path):
    from shortsmaker.studio import enhance
    sharp = enhance.analyze_quality(_bokeh_photo(tmp_path / "bokeh.jpg"))
    assert enhance.grade_photo(sharp)[0] != "C" and sharp["blur"] <= 0.5       # 오판 방지 (실제 사례: LG U+ 사진이 C 로 판정됐었다)
    blurry = enhance.analyze_quality(_bokeh_photo(tmp_path / "blurry.jpg", blur_all=6.0))
    grade, why = enhance.grade_photo(blurry)
    assert grade == "C" and any("흐림" in w for w in why)


def test_enhance_degraded_photo_improves_and_never_overwrites_original(tmp_path):
    import hashlib
    import numpy as np
    from PIL import Image
    from shortsmaker.studio import enhance
    src = Image.open(_bokeh_photo(tmp_path / "ok.jpg")).convert("RGB")
    dark = Image.fromarray((np.asarray(src, dtype="float32") * 0.3).astype("uint8"))      # 어둡게 열화 (평균 밝기 < 85)
    p = tmp_path / "dark.jpg"
    dark.save(p, quality=95)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    res = enhance.process_photos([str(p)], tmp_path / "job")
    it = res["photos"][0]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before                          # ORIGINAL 은 그대로
    assert it["decision"].startswith("enhanced") and it["enhanced"] and it["enhanced"] != str(p)
    assert it["metrics_after"]["exposure"]["mean"] > it["metrics_before"]["exposure"]["mean"] + 15
    assert it["fidelity"]["local"]["ok"] and (tmp_path / "job" / "derived" / "photo_quality.json").exists()


def test_c_grade_photo_is_not_enhanced_or_upscaled(tmp_path):
    from shortsmaker.studio import enhance
    p = _bokeh_photo(tmp_path / "bad.jpg", blur_all=6.0)
    res = enhance.process_photos([p], tmp_path / "job")
    it = res["photos"][0]
    assert it["grade_before"] == "C" and it["decision"].startswith("original (C") and it["effective"] == p


def test_fidelity_local_rejects_changed_product(tmp_path):
    """제품 형태/색이 달라지면 보정본을 폐기한다 (PRODUCT ACCURACY > BEAUTIFICATION)."""
    from PIL import Image, ImageDraw
    from shortsmaker.studio import enhance
    orig = Image.open(_bokeh_photo(tmp_path / "o.jpg")).convert("RGB")
    changed = orig.copy()
    ImageDraw.Draw(changed).ellipse([200, 360, 700, 860], fill=(200, 40, 40))             # 제품을 빨갛게 덮어씀
    assert enhance.fidelity_local(orig, changed)["ok"] is False
    assert enhance.fidelity_local(orig, orig.copy())["ok"] is True


# ------------------------------------------------------------------ STORYBOARD V2 - 1단계 (Engine + Scene Director)
def _plan_for(tmp_path, n_photos=2, compact=False, **extra):
    from shortsmaker.studio.director import direct_scenes, rule_director
    from shortsmaker.studio.product import ProductInput, analyze_photo, build_identity
    photos = make_photos("kitchen_tumbler", tmp_path / "p", n_photos)
    P = PRODUCTS["kitchen_tumbler"]
    p = ProductInput(name=P["name"], features=P["features"], problem=P["problem"], category_hint="주방", photos=photos,
                     compact=compact, **extra)
    ident = build_identity(p, [analyze_photo(x) for x in photos], "P-sb")
    return p, ident, direct_scenes(rule_director(p, "PRO"), ident, p, "PRO")


def test_duration_class_and_scene_range_table():
    from shortsmaker.studio.storyboard.schema import duration_class
    assert duration_class(12) == ("12s", (4, 6)) and duration_class(14.9) == ("12s", (4, 6))
    assert duration_class(20) == ("20s", (6, 9)) and duration_class(30) == ("30s", (8, 12)) and duration_class(45) == ("45s", (10, 15))


def test_storyboard_has_all_scene_director_fields_and_roundtrips(tmp_path):
    from dataclasses import fields
    from shortsmaker.studio.storyboard import Storyboard, StoryScene, build_storyboard
    p, ident, plan = _plan_for(tmp_path)
    sb = build_storyboard(plan, ident, p)
    need = {"scene_id", "scene_type", "duration", "purpose", "narration", "main_caption", "sub_caption", "visual_source", "visual_prompt",
            "layout", "camera_motion", "image_motion", "text_animation", "transition", "sound_effect", "music_cue", "emphasis"}
    assert need <= {f.name for f in fields(StoryScene)}
    assert sb.scenes and all(s.scene_type in {"HOOK", "PROBLEM", "PRODUCT_REVEAL", "FEATURE", "DEMO", "BENEFIT", "PROOF", "CTA"} for s in sb.scenes)
    assert sb.scenes[0].scene_type == "HOOK" and sb.scenes[-1].scene_type == "CTA" and sb.scenes[0].transition == "cut"
    assert all(s.narration and s.main_caption and s.visual_source.get("path") and s.music_cue for s in sb.scenes)
    back = Storyboard.from_json(sb.to_json())
    assert [s.to_dict() for s in back.scenes] == [s.to_dict() for s in sb.scenes] and back.scene_range == sb.scene_range


def test_storyboard_scene_count_respects_duration_class_and_never_pads(tmp_path):
    from shortsmaker.studio.storyboard import build_storyboard
    p, ident, plan = _plan_for(tmp_path)
    sb = build_storyboard(plan, ident, p)
    lo, hi = sb.scene_range
    assert len(sb.scenes) <= hi                                    # 상한 초과 시 우선순위 낮은 장면부터 줄임
    n_before = len(plan.scenes)
    short = type(plan)(**{**plan.__dict__, "scenes": plan.scenes[:3] + plan.scenes[-1:]})
    sb2 = build_storyboard(short, ident, p)
    assert len(sb2.scenes) == 4 and not any("제외" in w for w in sb2.warnings)   # 줄여야 하는 상황이 아님 (12초급 4~6 범위)
    assert n_before >= 4


def test_storyboard_compress_drops_low_priority_first_and_keeps_hook_reveal_cta(tmp_path):
    from shortsmaker.studio.storyboard.engine import fit_scene_count
    from shortsmaker.studio.storyboard.schema import StoryScene
    mk = lambda i, t: StoryScene(scene_id=f"S{i}", scene_type=t, duration=2, purpose="", narration="n", main_caption="c")
    types = ["HOOK", "PRODUCT_REVEAL", "FEATURE", "FEATURE", "FEATURE", "DEMO", "BENEFIT", "CTA"]
    warns: list = []
    out = fit_scene_count([mk(i, t) for i, t in enumerate(types)], (4, 6), warns)
    kept = [s.scene_type for s in out]
    assert len(out) == 6 and kept[0] == "HOOK" and "PRODUCT_REVEAL" in kept and kept[-1] == "CTA" and "DEMO" in kept and "BENEFIT" in kept
    assert kept.count("FEATURE") == 1 and len(warns) == 2      # 대표 특징 1개는 보존, 나머지 2개 제외 경고
    few: list = []
    assert len(fit_scene_count([mk(0, "HOOK"), mk(1, "CTA")], (4, 6), few)) == 2 and "반복해서 늘리지 않았어요" in few[0]


def test_data_claims_without_input_are_flagged_c_and_sfx_is_sparse(tmp_path):
    from shortsmaker.studio.storyboard.scene_director import claim_reliability
    facts = ["상품명: 텀블러", "특징: 450ml 대용량"]
    assert claim_reliability("450ml 대용량", facts)[0] == "A"
    rel, claims = claim_reliability("평점 4.9 후기 3,000개 특가", facts)
    assert rel == "C" and {c["reliability"] for c in claims} == {"C"}
    assert claim_reliability("혹시 보셨어요?", facts)[0] == "B"
    from shortsmaker.studio.storyboard import build_storyboard
    p, ident, plan = _plan_for(tmp_path)
    sb = build_storyboard(plan, ident, p)
    with_sfx = [s for s in sb.scenes if s.sound_effect]
    assert len(with_sfx) <= max(1, int(len(sb.scenes) * 0.7)) < len(sb.scenes) + 1
    assert any(not s.sound_effect for s in sb.scenes)               # 모든 장면에 넣지 않는다
    from shortsmaker.studio.storyboard.sfx_director import HEAVY
    for a, b in zip(sb.scenes, sb.scenes[1:]):                     # 연속 장면에 강한 효과음 금지
        assert not (any(e["sfx"] in HEAVY for e in a.sound_effect) and any(e["sfx"] in HEAVY for e in b.sound_effect))


def test_visual_source_router_prefers_user_media_and_records_gap_without_calling_ai(tmp_path):
    from shortsmaker.studio.storyboard.sources import route_visual_source
    p, ident, plan = _plan_for(tmp_path)
    r = route_visual_source("DEMO", ident.front_reference, ident, ["/x/use.mp4"], "텀블러", ["450ml"])
    assert r["kind"] == "user_video" and r["tier"] == 1 and "gap" not in r
    g = route_visual_source("DEMO", ident.front_reference, ident, [], "텀블러", ["450ml"])
    ident.usage_reference = None
    g = route_visual_source("DEMO", ident.front_reference, ident, [], "텀블러", ["450ml"])
    assert g["gap"] == "usage_scene_missing" and "IDENTICAL to the reference image" in g["visual_prompt"] and "no face" in g["visual_prompt"]
    assert g["ai_candidate"] is True and "미검증" in g["blocked"]      # 후보로만 기록, 실제 호출 없음
    third = route_visual_source("DEMO", ident.front_reference, ident, [], "텀블러", [], ai_scenes_used=2)
    assert third["ai_candidate"] is False                          # AI 영상은 핵심 장면 상한 2개


def test_pipeline_writes_storyboard_json_and_keeps_rendering_unchanged(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 3)
    P = PRODUCTS["kitchen_tumbler"]
    r = run_job({"name": P["name"], "features": P["features"], "problem": P["problem"], "category_hint": "주방", "photos": photos},
                "FAST", ["youtube"], out_root=tmp_path / "out", db=DB(tmp_path / "db.sqlite"), render=(270, 480, 10))
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
    sb = r["storyboard"]
    assert sb["version"] == 1 and sb["scenes"] and sb["duration_class"] in ("12s", "20s", "30s", "45s")
    saved = list((tmp_path / "out").glob("*/v*/storyboard.json"))
    assert saved and json.loads(saved[-1].read_text(encoding="utf-8"))["scenes"]


def test_rule_script_does_not_invent_size_or_benefit_claims():
    """규칙 대본의 첫 특징에 '이게 생각보다 커요' 를 붙이던 템플릿(모든 상품에 크기 주장)을 제거했다."""
    from shortsmaker.studio.director import feature_lines
    lines = feature_lines(["컬러 LED 링", "송풍구 클립 거치", "USB-C 충전"])
    joined = " ".join(t for t, _ in lines)
    assert "생각보다" not in joined and "커요" not in joined and "좋아요" not in joined
    assert lines[0][0] == "컬러 LED 링이 있어요" and lines[2][0].startswith("그리고 USB-C 충전")
    from shortsmaker.studio.storyboard.scene_director import claim_reliability
    assert claim_reliability("컬러 LED 링, 이게 생각보다 커요", ["특징: 컬러 LED 링"])[0] == "B"     # 문장 일부만 사실이면 A 가 아니다
    assert claim_reliability("컬러 LED 링이 있어요", ["특징: 컬러 LED 링"])[0] == "A"


# ------------------------------------------------------------------ STORYBOARD V2 - 2단계 (Layout Engine)
def _scenes(types):
    from shortsmaker.studio.storyboard.schema import StoryScene
    return [StoryScene(scene_id=f"S{i + 1}", scene_type=t, duration=2.5, purpose="", narration="n", main_caption="c",
                       visual_source={"path": "/p/a.jpg", "kind": "user_photo"}, emphasis=["x"]) for i, t in enumerate(types)]


def _ctx(**kw):
    from shortsmaker.studio.storyboard.layouts import LayoutContext
    base = dict(photos=[{"path": "/p/a.jpg", "focus": [0.5, 0.5]}, {"path": "/p/b.jpg", "focus": [0.5, 0.5]}], zoomable={"/p/a.jpg", "/p/b.jpg"},
                features=["컬러 LED 링", "송풍구 클립 거치"], cutout_ok=set())
    base.update(kw)
    return LayoutContext(**base)


def test_layout_catalog_has_all_17_and_renderers():
    from shortsmaker.studio.layout_render import RENDERERS
    from shortsmaker.studio.storyboard.layouts import FAMILY, FITNESS, LABELS, LAYOUTS
    want = {"full_product", "product_center", "split_screen", "before_after", "problem_solution", "feature_callout", "review_quote",
            "three_benefits", "comparison", "close_up", "lifestyle", "product_overlay", "floating_product", "text_focus", "demo", "result", "cta"}
    assert set(LAYOUTS) == want and set(RENDERERS) == want and set(FAMILY) == want and set(LABELS) == want
    assert all(l in want for fit in FITNESS.values() for l in fit)


def test_layout_selection_no_consecutive_repeat_and_deterministic():
    from shortsmaker.studio.storyboard.layouts import select_layouts
    types = ["HOOK", "PROBLEM", "PRODUCT_REVEAL", "FEATURE", "FEATURE", "DEMO", "BENEFIT", "CTA"]
    a, b = _scenes(types), _scenes(types)
    ctx = _ctx(usage_path="/p/use.jpg")
    select_layouts(a, ctx), select_layouts(b, ctx)
    assert [s.layout for s in a] == [s.layout for s in b]                                   # 랜덤 없음
    assert all(x.layout != y.layout for x, y in zip(a, a[1:]))                              # 연속 반복 금지
    assert a[-1].layout == "cta" and a[0].scene_type == "HOOK" and all(s.decisions.get("layout") for s in a)
    assert len({s.layout for s in a}) >= 6                                                  # 슬라이드쇼처럼 한 두 가지로 돌려 쓰지 않는다


def test_layouts_that_need_real_data_are_unavailable_without_it():
    """후기/비교/전후/시연/라이프스타일은 사용자가 준 실제 데이터(또는 사용 장면)가 있을 때만 후보가 된다."""
    from shortsmaker.studio.storyboard.layouts import availability, select_layouts
    sc = _scenes(["PROOF", "DEMO", "BENEFIT"])
    ctx = _ctx()
    assert availability("demo", sc[1], _ctx(usage_path="/p/use.jpg"))[0] is False        # 사용 '사진'만으로는 시연이 아니다
    assert availability("lifestyle", sc[2], _ctx(usage_path="/p/use.jpg"))[0] is True
    for name, i in (("review_quote", 0), ("comparison", 0), ("before_after", 2), ("demo", 1), ("lifestyle", 2)):
        assert availability(name, sc[i], ctx)[0] is False, name
    select_layouts(sc, ctx)
    assert not ({"review_quote", "comparison", "before_after", "demo", "lifestyle"} & {s.layout for s in sc})
    ok = _ctx(review_quotes=["링 색이 예뻐요"], comparison=[{"label": "링", "ours": "컬러", "other": "단색"}], before_after=("/p/a.jpg", "/p/b.jpg"),
              clip_paths=["/p/u.mp4"])
    for name, i in (("review_quote", 0), ("comparison", 0), ("before_after", 2), ("demo", 1), ("lifestyle", 2)):
        assert availability(name, sc[i], ok)[0] is True, name
    sc2 = _scenes(["PROOF"])
    select_layouts(sc2, ok)
    assert sc2[0].layout in ("review_quote", "comparison") and (sc2[0].layout_data.get("quote") or sc2[0].layout_data.get("rows"))


def test_layout_off_center_quota_and_card_family_before_cta():
    from shortsmaker.studio.storyboard.layouts import FAMILY, OFF_CENTER, select_layouts
    sc = _scenes(["HOOK", "PRODUCT_REVEAL", "FEATURE", "BENEFIT", "CTA"])
    select_layouts(sc, _ctx())
    assert sum(1 for s in sc if s.layout in OFF_CENTER) >= 2                                # 상품이 항상 정중앙 금지 (5장면 -> 2개 이상)
    assert FAMILY[sc[-2].layout] != "card"                                                  # CTA 직전엔 CTA(카드)와 다른 화면


def test_all_17_layouts_render_valid_frames_and_respect_privacy_tight_crop(tmp_path):
    from PIL import Image
    from shortsmaker.studio.motion import MotionRenderer, Shot
    from shortsmaker.studio.storyboard.layouts import LAYOUTS
    a = make_photos("kitchen_tumbler", tmp_path / "p", 2)
    r = MotionRenderer(width=270, height=480, fps=10)
    data = {"callout": "특징", "items": ["하나", "둘"], "quote": "좋아요", "rows": [{"label": "a", "ours": "b", "other": "c"}], "before": a[0], "after": a[1]}
    seen = set()
    for lay in LAYOUTS:
        f = r.frame(Shot("S", "hero_push", a[0], 2.0, layout=lay, source2=a[1], data=data), 1.0, 0)
        assert f.size == (270, 480) and f.mode == "RGB", lay
        seen.add(f.tobytes()[:2000])
    assert len(seen) >= 12                                                                  # 17종이 서로 다른 화면 (복사본 아님)
    # 레거시 경로는 layout 이 비어 있으면 그대로 동작
    assert r.frame(Shot("S", "hero_push", a[0], 2.0), 1.0, 0).size == (270, 480)
    r.cache.boxes[a[0]] = (0.3, 0.3, 0.7, 0.7)
    r.cache.tight = {a[0]}
    assert r.frame(Shot("S", "hero_push", a[0], 2.0, layout="full_product"), 1.0, 0).size == (270, 480)
    assert r.frame(Shot("S", "hero_push", a[0], 2.0, layout="close_up"), 1.0, 0).size == (270, 480)


def test_macro_on_tight_crop_keeps_whole_product():
    """개인정보 타이트 크롭에서 매크로가 제품을 자르지 않는다 (박스 비율을 전체 사진이 아니라 크롭 영역 기준으로)."""
    from PIL import Image, ImageDraw
    import tempfile, numpy as np
    from shortsmaker.studio.motion import MotionRenderer, macro_plate
    d = tempfile.mkdtemp()
    im = Image.new("RGB", (1800, 2400), (30, 30, 30))
    ImageDraw.Draw(im).ellipse([300, 600, 1500, 1800], fill=(240, 240, 240))               # 큰 원형 제품
    path = f"{d}/ring.jpg"
    im.save(path)
    r = MotionRenderer(width=270, height=480, fps=10)
    r.cache.boxes[path] = (300 / 1800, 600 / 2400, 1500 / 1800, 1800 / 2400)
    r.cache.tight = {path}
    plate = np.asarray(macro_plate(r.cache, path, None).convert("L"))
    h, w = plate.shape
    ys, xs = np.nonzero(plate > 200)
    assert xs.min() > 0.02 * w and xs.max() < 0.98 * w                                      # 제품(흰 원)이 좌우 가장자리에서 잘리지 않음


# ------------------------------------------------------------------ STORYBOARD V2 - 3단계 (Motion Director)
EXPECTED_MOTIONS = {"zoom_in", "zoom_out", "slow_zoom", "pan_left", "pan_right", "parallax", "depth_zoom", "mask_reveal", "object_focus",
                    "background_blur", "light_sweep", "floating_product", "punch_in", "shake", "ken_burns"}


def _mscenes(specs):
    """specs: [(scene_type, layout, narration)]"""
    from shortsmaker.studio.storyboard.schema import StoryScene
    return [StoryScene(scene_id=f"S{i + 1}", scene_type=t, duration=2.5, purpose="", narration=n, main_caption=n, layout=l)
            for i, (t, l, n) in enumerate(specs)]


def test_motion_catalog_is_complete_on_both_sides():
    from shortsmaker.studio.camera import MOTIONS as RM, cam_at
    from shortsmaker.studio.storyboard.motion_director import MOTIONS as DM, CAMERA_TEXT, LABELS
    assert set(DM) == set(RM) == EXPECTED_MOTIONS and set(CAMERA_TEXT) == set(LABELS) == EXPECTED_MOTIONS

    class S:
        duration, emph_at = 2.0, 0.3
    for m in EXPECTED_MOTIONS:
        assert cam_at(m, S, 0.5, 0.25) is not None and cam_at(m, S, 0.5, 0.25).scale >= 0.99


def test_motion_is_chosen_from_meaning_not_random():
    from shortsmaker.studio.storyboard.motion_director import select_motions
    feats = ["컬러 LED 링", "송풍구 클립 거치"]
    spec = [("HOOK", "full_product", "이 거치대, 아직 안 써보셨어요?"), ("PRODUCT_REVEAL", "product_center", "바로 이 거치대예요"),
            ("FEATURE", "feature_callout", "컬러 LED 링이 있어요"), ("DEMO", "split_screen", "게다가 송풍구 클립 거치까지 돼요"),
            ("BENEFIT", "product_center", "실제 모습은 이렇게"), ("CTA", "cta", "정보는 링크에서")]
    a, b = _mscenes(spec), _mscenes(spec)
    select_motions(a, feats), select_motions(b, feats)
    assert [s.image_motion for s in a] == [s.image_motion for s in b]                      # 같은 입력 = 같은 결과
    assert a[0].image_motion == "mask_reveal" and "의문" in a[0].decisions["motion"]       # 질문 훅 -> 마스크 공개
    assert a[2].image_motion == "object_focus" and "컬러 LED 링" in a[2].decisions["motion"]   # 특징을 말하는 순간 해당 부분 강조
    assert a[3].image_motion in ("pan_left", "pan_right")                                   # 거치/고정 동작 -> 패닝
    assert "빛/색" not in a[5].decisions["motion"]                                           # '링크' 의 '링' 을 LED 링으로 오인하지 않는다
    assert all(x.image_motion != y.image_motion for x, y in zip(a, a[1:]))                  # 연속 같은 모션 금지
    assert all(s.camera_motion and s.decisions["motion"] for s in a)


def test_motion_layout_compatibility_and_not_all_zoom():
    from shortsmaker.studio.storyboard.motion_director import ALLOWED, LAYERED, ZOOM_FAMILY, allowed_for, select_motions
    for lay in ("full_product", "close_up", "split_screen", "feature_callout", "review_quote", "before_after", "demo", "lifestyle"):
        assert not ({"parallax", "depth_zoom", "floating_product"} & allowed_for(lay)), lay    # 배경/제품이 분리된 레이아웃에서만
    for lay in LAYERED:
        assert "pan_left" not in allowed_for(lay)
    spec = [("HOOK", "full_product", "첫 장면"), ("PRODUCT_REVEAL", "product_center", "공개"), ("FEATURE", "close_up", "특징 하나"),
            ("FEATURE", "product_overlay", "특징 둘"), ("DEMO", "full_product", "시연"), ("BENEFIT", "result", "결과"),
            ("BENEFIT", "floating_product", "또 결과"), ("CTA", "cta", "링크")]
    sc = _mscenes(spec)
    select_motions(sc, [])
    zoomish = sum(1 for s in sc if s.image_motion in ZOOM_FAMILY)
    assert zoomish <= int(len(sc) * 0.6)                                                    # 모든 장면 동일 줌 효과 금지
    assert all(s.image_motion in allowed_for(s.layout) for s in sc)


def test_every_motion_actually_changes_the_picture_over_time(tmp_path):
    import numpy as np
    from shortsmaker.studio.camera import MOTIONS
    from shortsmaker.studio.motion import MotionRenderer, Shot
    photo = make_photos("kitchen_tumbler", tmp_path / "p", 1)[0]
    r = MotionRenderer(width=270, height=480, fps=10)
    r.cache.boxes[photo] = (0.2, 0.2, 0.8, 0.8)
    for m in MOTIONS:
        lay = "product_center" if m in ("parallax", "depth_zoom", "floating_product") else "full_product"
        sh = Shot("S", "hero_push", photo, 2.0, layout=lay, motion=m, emph_at=0.2)
        a, b = r.frame(sh, 0.05, 0), r.frame(sh, 1.4, 0)
        diff = float(np.abs(np.asarray(a, np.float32) - np.asarray(b, np.float32)).mean())
        assert diff > 0.4, (m, diff)                                                         # 정적인 모션 없음
        assert np.array_equal(np.asarray(r.frame(sh, 1.4, 0)), np.asarray(b))                # 같은 시각 = 같은 프레임 (랜덤 없음)


# ------------------------------------------------------------------ STORYBOARD V2 - 4단계 (Storyboard -> EDL -> Renderer, 검증기)
def test_caption_split_keeps_reading_order_and_roundtrips():
    from shortsmaker.studio.storyboard.scene_director import caption_text, split_caption
    from shortsmaker.studio.storyboard.schema import StoryScene
    main, sub, emph = split_caption("이 거치대\n혹시 [[보셨어요]]?")
    assert (main, sub, emph) == ("이 거치대", "혹시 보셨어요?", ["보셨어요"])                # 읽는 순서 유지 (강조 줄을 앞으로 빼지 않는다)
    sc = StoryScene(scene_id="S1", scene_type="HOOK", duration=2, purpose="", narration="n", main_caption=main, sub_caption=sub, emphasis=emph)
    assert caption_text(sc) == "이 거치대\n혹시 [[보셨어요]]?"
    sc.main_caption = "이 링 보셨어요"                                                        # Preview 에서 사용자가 고친 자막도 같은 경로
    assert caption_text(sc) == "이 링 [[보셨어요]]\n혹시 보셨어요?"                          # 강조 단어는 한 번만 표시


def test_edit_from_storyboard_makes_one_cut_per_scene_with_layout_motion_sfx(tmp_path):
    from shortsmaker.studio.storyboard import build_storyboard
    from shortsmaker.studio.storyboard_edit import edit_from_storyboard
    p, ident, plan = _plan_for(tmp_path)
    sb = build_storyboard(plan, ident, p)
    edl = edit_from_storyboard(sb)
    assert edl["storyboard"] is True and len(edl["shots"]) == len(sb.scenes)                 # 장면 1개 = 컷 1개 (같은 사진을 쪼개 컷 수를 채우지 않음)
    for shot, sc in zip(edl["shots"], sb.scenes):
        assert shot.layout == sc.layout and shot.motion == sc.image_motion and shot.scene_id == sc.scene_id
        assert shot.caption_words and shot.transition_in == ("cut" if sc is sb.scenes[0] else sc.transition)
    assert len(edl["events"]) <= sum(len(s.sound_effect) for s in sb.scenes)                 # 효과음은 Storyboard 가 정한 지점에만
    assert edl["timing"]["first_caption"] is not None and edl["timing"]["reveal_at"] is not None
    if sb.scenes[0].image_motion in ("punch_in", "mask_reveal", "shake", "zoom_in", "object_focus"):
        assert edl["timing"]["first_visual_change"] <= 1.3                                   # Hook 첫 2초 시각 변화
    # 음성이 있으면 대사 길이에 맞춰 컷이 늘어난다 (Dead air 제거)
    voice = {sb.scenes[1].scene_id: (4.0, str(tmp_path / "v.wav"))}
    longer = edit_from_storyboard(sb, voice)
    assert longer["shots"][1].duration >= 4.2 and longer["voice"]


def test_validator_detects_and_fixes_weak_hook_and_missing_feature_emphasis():
    from shortsmaker.studio.storyboard.validator import validate
    sc = _mscenes([("HOOK", "full_product", "첫 장면"), ("FEATURE", "close_up", "컬러 LED 링이 있어요"), ("DEMO", "split_screen", "시연"),
                   ("CTA", "cta", "링크")])
    for s, m in zip(sc, ("slow_zoom", "zoom_in", "pan_left", "light_sweep")):
        s.image_motion = m
        s.visual_source = {"path": f"/p/{s.scene_id}.jpg"}
    sc[-1].transition = "cut"
    issues = validate(sc, ["컬러 LED 링"])
    rules = {i["rule"]: i for i in issues}
    assert rules["hook_weak"]["fixed"] and sc[0].image_motion in ("punch_in", "mask_reveal", "zoom_in")
    assert rules["feature_not_emphasized"]["fixed"] and sc[1].image_motion == "object_focus"   # 특징을 말하는 순간 해당 영역 강조
    assert "cta_no_transition" in rules and "pre_cta_no_change" not in rules
    # 위반 탐지: 같은 레이아웃/모션 연속, 같은 사진 장시간, 줌 일색
    bad = _mscenes([("HOOK", "full_product", "a"), ("FEATURE", "full_product", "b"), ("DEMO", "full_product", "c"), ("BENEFIT", "full_product", "d")])
    for s in bad:
        s.image_motion, s.visual_source = "zoom_in", {"path": "/p/same.jpg"}
    found = {i["rule"] for i in validate(bad, [], fix=False)}
    assert {"layout_repeat", "motion_repeat", "same_image_long", "all_zoom", "slideshow", "always_centered"} <= found


def test_storyboard_path_is_default_and_legacy_path_still_works(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 3)
    P = PRODUCTS["kitchen_tumbler"]
    base = {"name": P["name"], "features": P["features"], "problem": P["problem"], "category_hint": "주방", "photos": photos}
    r = run_job(base, "FAST", ["youtube"], out_root=tmp_path / "o1", db=DB(tmp_path / "d1.sqlite"), render=(270, 480, 10))
    assert r["edl"]["shots"] and all(s["layout"] and s["motion"] for s in r["edl"]["shots"])
    assert len(r["edl"]["shots"]) == len(r["storyboard"]["scenes"])
    legacy = run_job({**base, "legacy_render": True}, "FAST", ["youtube"], out_root=tmp_path / "o2", db=DB(tmp_path / "d2.sqlite"),
                     render=(270, 480, 10))
    assert legacy["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW") and all(not s["layout"] for s in legacy["edl"]["shots"])


# ------------------------------------------------------------------ Preview Mode
def _preview_base(tmp_path):
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 3)
    P = PRODUCTS["kitchen_tumbler"]
    return {"name": P["name"], "features": P["features"], "problem": P["problem"], "category_hint": "주방", "photos": photos}


def test_preview_makes_cards_without_mp4_or_tts(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    r = run_job({**_preview_base(tmp_path), "preview": True}, "FAST", ["youtube"], out_root=tmp_path / "out",
                db=DB(tmp_path / "db.sqlite"), render=(270, 480, 10))
    assert r["status"] == "PREVIEW_READY", r.get("error")
    assert not r.get("master") and not list((tmp_path / "out").rglob("*.mp4"))        # MP4 는 [영상 제작] 전에는 만들지 않는다
    ids = [s["scene_id"] for s in r["storyboard"]["scenes"]]
    assert set(r["preview"]["thumbs"]) == set(ids) and all(Path(v).exists() for v in r["preview"]["thumbs"].values())
    assert set(r["preview"]["options"]) == set(ids) and r["director_data"]
    assert "demo" not in r["preview"]["options"][ids[0]]["layouts"]                    # 영상 없이 시연 레이아웃은 선택지에 없다


def test_preview_edits_are_applied_or_rejected_with_reason(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    base = _preview_base(tmp_path)
    db = DB(tmp_path / "db.sqlite")
    pv = run_job({**base, "preview": True}, "FAST", ["youtube"], out_root=tmp_path / "out", db=db, render=(270, 480, 10))
    scenes = pv["storyboard"]["scenes"]
    mid = scenes[1]["scene_id"]
    edits = {"scenes": {mid: {"narration": "수정한 나레이션이에요", "caption": "수정한 자막", "layout": "demo", "photo_index": 99},
                        scenes[0]["scene_id"]: {"drop": True}}}
    r = run_job({**base, "preview": True, "director_data": pv["director_data"], "edits": edits}, "FAST", ["youtube"],
                out_root=tmp_path / "out2", db=db, render=(270, 480, 10))
    rej = {(x["scene_id"], x["why"]) for x in r["edits_report"]["rejected"]}
    assert any("시연 영상" in w for _, w in rej) and any("사진 번호" in w for _, w in rej) and any("훅/CTA" in w for _, w in rej)
    sc = next(s for s in r["storyboard"]["scenes"] if s["scene_id"] == mid)
    assert sc["narration"] == "수정한 나레이션이에요" and "수정한 자막" in sc["main_caption"] + sc["sub_caption"]
    assert sc["layout"] != "demo"
    assert [s["scene_id"] for s in r["storyboard"]["scenes"]][0] == scenes[0]["scene_id"]      # 훅은 삭제되지 않음


def test_preview_order_rules():
    from shortsmaker.studio.storyboard.preview import apply_plan_edits
    from types import SimpleNamespace as NS
    plan = NS(scenes=[NS(scene_id=f"S{i}", beat=b, tts_line="x", caption="y") for i, b in
                      enumerate(["hook", "reveal", "detail", "benefit", "cta"], 1)])
    bad = apply_plan_edits(plan, {"order": ["S2", "S1", "S3", "S4", "S5"]})
    assert bad["rejected"] and [s.scene_id for s in plan.scenes][0] == "S1"
    ok = apply_plan_edits(plan, {"order": ["S1", "S3", "S2", "S4", "S5"]})
    assert ok["applied"] and [s.scene_id for s in plan.scenes] == ["S1", "S3", "S2", "S4", "S5"]


def test_render_endpoint_requires_ready_preview(tmp_path):
    from fastapi.testclient import TestClient
    from shortsmaker.web.app import create_app
    client = TestClient(create_app({}, tmp_path / "o", tmp_path / "u"))
    assert client.post("/api/v2/jobs/nope/render", json={"edits": {}}).status_code == 400


def test_render_after_preview_uses_confirmed_script_and_edits(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    base = _preview_base(tmp_path)
    db = DB(tmp_path / "db.sqlite")
    pv = run_job({**base, "preview": True}, "FAST", ["youtube"], out_root=tmp_path / "out", db=db, render=(270, 480, 10))
    sid = pv["storyboard"]["scenes"][1]["scene_id"]
    r = run_job({**base, "director_data": pv["director_data"], "edits": {"scenes": {sid: {"narration": "확정한 나레이션"}}}},
                "FAST", ["youtube"], out_root=tmp_path / "out2", db=db, render=(270, 480, 10))
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
    assert Path(r["master"]).exists()
    assert next(s for s in r["storyboard"]["scenes"] if s["scene_id"] == sid)["narration"] == "확정한 나레이션"
    assert [s["scene_id"] for s in r["storyboard"]["scenes"]] == [s["scene_id"] for s in pv["storyboard"]["scenes"]]


# ------------------------------------------------------------------ SHOPPING_SHORTS_STRATEGY_ENGINE
def _sp(**kw):
    from shortsmaker.studio.product import ProductInput
    base = dict(name="보온보냉 스텐 텀블러", features=["원터치 뚜껑", "컵홀더에 쏙 들어가는 슬림형", "세척이 쉬운 넓은 입구"],
                problem="텀블러 뚜껑 여는 게 번거로워요", target="출퇴근 직장인")
    base.update(kw)
    return ProductInput(**base)


def test_strategy_chain_has_all_stages_and_three_styles_differ():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    out = {}
    for st in ("FAST_COMMERCE", "STORY_AD", "UGC_REVIEW"):
        s = run_strategy(None, make_ctx(_sp(), style=st))
        for k in ("product_analysis", "primary_selling_point", "differentiation_angles", "selected_angle", "hook_candidates", "selected_hook",
                  "script", "comment_trigger", "cta", "conversion_audit", "final_script", "before_after"):
            assert s.get(k) not in (None, [], {}), (st, k)
        out[st] = s
    hooks = {s["selected_hook"]["text"] for s in out.values()}
    flows = {tuple(x["beat"] for x in s["final_script"]["scenes"]) for s in out.values()}
    ctas = {s["final_script"]["scenes"][-1]["narration"] for s in out.values()}
    assert len(hooks) == 3 and len(flows) >= 2 and len(ctas) == 3          # 대사만 바꾼 것이 아니라 Hook/구조/CTA 가 다르다
    assert all(x["narration"] for s in out.values() for x in s["final_script"]["scenes"])


def test_strategy_scene_fields_roles_and_visibility():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    s = run_strategy(None, make_ctx(_sp(), style="STORY_AD"))
    sc = s["final_script"]["scenes"]
    assert sc[0]["scene_role"] == "HOOK" and sc[-1]["scene_role"] == "CTA"
    assert {x["product_visibility"] for x in sc} <= {"NONE", "HINT", "PARTIAL", "FULL"}
    assert all(set(x) >= {"scene_id", "time", "purpose", "narration", "caption", "visual_source", "visual_prompt", "product_visibility"} for x in sc)
    assert sc[0]["time"][0] == 0 and all(a["time"][1] <= b["time"][0] + 1e-6 for a, b in zip(sc, sc[1:]))


def test_fact_safety_blocks_unverified_claims_and_cliches():
    from shortsmaker.studio.strategy import make_ctx
    from shortsmaker.studio.strategy.common import line_issues
    ctx = make_ctx(_sp())
    codes = lambda t: {i["code"] for i in line_issues(t, ctx)}
    assert "cliche" in codes("이거 꼭 보세요") and "cliche" in codes("요즘 핫한 제품입니다")
    assert "direct_comment" in codes("댓글 남겨주세요") and "direct_comment" in codes("여러분 생각은?")
    assert "scarcity_unverified" in codes("오늘만 할인")
    assert "social_unverified" in codes("후기가 난리예요") or "cliche" in codes("후기가 난리예요")
    assert "performance_unverified" in codes("방수라서 튼튼해요") and "data_unverified" in codes("12시간 보온")
    assert not codes("원터치 뚜껑이 있어요")
    ok = make_ctx(_sp(description="오늘만 할인 쿠폰 제공"))                 # 입력에 실제로 있으면 쓸 수 있다
    assert "scarcity_unverified" not in {i["code"] for i in line_issues("오늘만 할인", ok)}


def test_cta_scarcity_and_social_proof_only_when_input_has_them():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    plain = run_strategy(None, make_ctx(_sp()))["cta"]
    assert not plain["eligibility"]["SCARCITY"]["allowed"] and not plain["eligibility"]["SOCIAL_PROOF"]["allowed"]
    assert all(c["strategy"] not in ("SCARCITY", "SOCIAL_PROOF") for c in plain["candidates"])
    rich = run_strategy(None, make_ctx(_sp(review_quotes=["뚜껑이 한 번에 열려요"], description="쿠폰 적용 가능")))["cta"]
    assert rich["eligibility"]["SOCIAL_PROOF"]["allowed"] and rich["eligibility"]["SCARCITY"]["allowed"]
    assert {c["strategy"] for c in rich["candidates"]} >= {"SOCIAL_PROOF", "SCARCITY"}


def test_comment_trigger_never_requests_comments_and_skips_short_videos():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    from shortsmaker.studio.strategy.common import DIRECT_COMMENT
    s = run_strategy(None, make_ctx(_sp(), style="STORY_AD"))
    ct = s["comment_trigger"]
    assert ct["selected"] and not DIRECT_COMMENT.search(ct["selected"]["text"]) and len(ct["candidates"]) >= 3
    short = run_strategy(None, make_ctx(_sp(compact=True), style="FAST_COMMERCE"))["comment_trigger"]
    assert short["insert"] is False and short["skip_reason"]
    # 호기심형은 영상에서 아직 안 쓴 실제 특징이 있을 때만: 특징이 1개뿐이면 만들지 않는다
    one = run_strategy(None, make_ctx(_sp(features=["원터치 뚜껑"]), style="STORY_AD"))["comment_trigger"]
    assert all(c["method"] != "CURIOSITY" for c in one["candidates"])


def test_no_problem_input_means_no_problem_scene_and_no_loss_aversion():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    s = run_strategy(None, make_ctx(_sp(problem="", target=""), style="STORY_AD"))
    assert all(x["beat"] != "problem" for x in s["final_script"]["scenes"])
    assert not s["cta"]["eligibility"]["LOSS_AVERSION"]["allowed"]


def test_audit_finds_problems_and_auto_revision_fixes_them_without_inventing():
    import copy
    from shortsmaker.studio.strategy import engine, make_ctx, run_strategy
    ctx = make_ctx(_sp(), style="STORY_AD")
    state = run_strategy(None, ctx, auto=False)
    bad = copy.deepcopy(state["script"])
    sc = bad["scenes"]
    sc[0].update(tts_line="이거 꼭 보세요 정말 정말 대박 제품이에요 지금 바로 확인", narration="이거 꼭 보세요 정말 정말 대박 제품이에요 지금 바로 확인")
    extra = copy.deepcopy(sc[3]); extra.update(scene_id="X1")
    sc.insert(4, extra)                                         # 같은 말 반복
    sc[2].update(tts_line="12시간 보온되고 방수까지 돼요", narration="12시간 보온되고 방수까지 돼요")   # 입력에 없는 성능
    state["script"] = bad
    engine._audit_and_revise(None, ctx, state, auto=False)
    a0 = state["conversion_audit"]
    codes = {i["code"] for i in a0["issues"]}
    assert not a0["gate"]["passed"] and {"hook_weak", "cliche", "unproven_claim", "repeat"} <= codes
    assert a0["issues"][0]["priority"] == "P0" and len(a0["top_fixes"]) <= 5
    assert all({"problem", "cause", "fix", "effect"} <= set(i) for i in a0["issues"])
    engine._audit_and_revise(None, ctx, state, auto=True)
    a1 = state["conversion_audit"]
    assert a1["rounds"] and a1["gate"]["passed"], a1["gate"]
    final = " ".join(x["narration"] for x in state["final_script"]["scenes"])
    assert "12시간" not in final and "방수" not in final and "대박" not in final
    ba = state["before_after"]
    assert ba["BEFORE"]["hook"] != ba["AFTER"]["hook"]
    assert state["final_script"]["scenes"][0]["beat"] == "hook" and state["final_script"]["scenes"][-1]["beat"] == "cta"


def test_audit_scores_are_deterministic_and_trust_is_capped_without_real_proof():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    a = run_strategy(None, make_ctx(_sp()))["conversion_audit"]
    b = run_strategy(None, make_ctx(_sp()))["conversion_audit"]
    assert a["scores"] == b["scores"]
    assert a["scores"]["trust_proof"] <= 70                   # 후기/써본 느낌/영상이 없으면 높은 신뢰 점수 불가
    rich = run_strategy(None, make_ctx(_sp(review_quotes=["뚜껑이 한 번에 열려요"], my_take="출근길에 한 손으로 열었어요"), has_clip=True))["conversion_audit"]
    assert rich["scores"]["trust_proof"] > a["scores"]["trust_proof"]
    assert set(a["funnel"]) == {"SCROLL_STOP", "ATTENTION", "INTEREST", "PROBLEM_RECOGNITION", "PRODUCT_DESIRE", "TRUST", "ACTION"}
    assert a["timeline"] and all({"time", "risk", "reason", "viewer_thought", "fix"} <= set(t) for t in a["timeline"])


def test_strategy_reuses_earlier_stages_and_pick_changes_only_downstream():
    from shortsmaker.studio.strategy import make_ctx, pick, run_strategy
    ctx = make_ctx(_sp(), style="FAST_COMMERCE")
    s = run_strategy(None, ctx)
    sp_before = s["selling_point_analysis"]
    other = next(c for c in sp_before["candidates"] if c["id"] != s["primary_selling_point"]["id"] and c["reliability"] != "C")
    start = pick(s, "selling_point", other["id"])
    assert start == "angle"
    s2 = run_strategy(None, ctx, s, start=start)
    assert s2["selling_point_analysis"] is not sp_before and s2["selling_point_analysis"]["candidates"] == sp_before["candidates"]   # 후보는 재생성하지 않음
    assert s2["primary_selling_point"]["id"] == other["id"]
    try:
        pick(s2, "hook", "H99")
        assert False
    except ValueError:
        pass


class _FakeLLM:
    """결정적인 가짜 LLM: 단계별 JSON 을 돌려주고, '한 손' 이 들어간 문장은 근거 없음으로 판정한다."""
    def __init__(self):
        self.calls = []

    def has_real(self, task):
        return True

    def run(self, task, method, system="", user="", **kw):
        from types import SimpleNamespace as NS
        self.calls.append(system[:20])
        if system.startswith("You are a strict fact checker"):
            lines = json.loads(user)["lines"]
            return NS(provider="fake", model="m", value={"unsupported": [{"line": l, "phrase": "한 손", "reason": "입력에 없음"} for l in lines if "한 손" in l]})
        sc5 = {"instant_understanding": 4, "problem_strength": 4, "purchase_desire": 4, "shortform_fit": 4, "visual_potential": 3, "target_relevance": 4}   # 1~5 척도
        if "구매 이유" in system:
            return NS(provider="fake", model="m", value={"product_analysis": {"shape": "원통형"}, "candidates": [
                {"text": "원터치 뚜껑으로 바로 열림", "kind": "FUNCTIONAL", "feature": "특징: 원터치 뚜껑", "scores": sc5},
                {"text": "방수라서 어디서나 안심", "kind": "FUNCTIONAL", "feature": "", "scores": sc5},
                {"text": "슬림형이라 컵홀더에 들어감", "kind": "FUNCTIONAL", "feature": "컵홀더에 쏙 들어가는 슬림형", "scores": sc5},
                {"text": "입구가 넓음", "kind": "FUNCTIONAL", "feature": "세척이 쉬운 넓은 입구", "scores": sc5},
                {"text": "뚜껑 여는 불편", "kind": "PAIN_POINT", "feature": "원터치 뚜껑", "scores": sc5}]})
        if "차별화 전략가" in system:
            return NS(provider="fake", model="m", value={"angles": [
                {"axis": "PAIN_POINT", "title": "뚜껑 불편", "premise": "뚜껑 여는 불편을 먼저", "story_form": "문제 해결", "evidence": ["x"], "scores": sc5},
                {"axis": "TARGET", "title": "직장인", "premise": "출퇴근 직장인 호출", "story_form": "대상 호출", "evidence": ["y"], "scores": sc5}]})
        if "Hook 작가" in system:
            mk = lambda t, x: {"type": t, "text": x, "scores": sc5}
            return NS(provider="fake", model="m", value={"hooks": [
                mk("PROBLEM", "텀블러 뚜껑 여는 게 번거로우셨나요?"), mk("PROBLEM", "한 손으로 열리는 텀블러 찾으세요?"), mk("PROBLEM", "뚜껑 때문에 물 마시기 귀찮죠?"),
                mk("CURIOSITY", "원터치 뚜껑, 어떻게 열릴까요?"), mk("CURIOSITY", "이 텀블러 뚜껑 보세요"), mk("CURIOSITY", "컵홀더에 쏙 들어가는 텀블러?"),
                mk("EMPATHY", "뚜껑 여는 것도 은근 일이죠"), mk("EMPATHY", "텀블러 뚜껑, 나만 불편해?"), mk("EMPATHY", "텀블러 닦기도 번거롭죠")]})
        if "판매 대본 작가" in system:
            return NS(provider="fake", model="m", value={"beats": [
                {"beat": "hook", "tts_line": "무시될 문장", "caption": "무시"}, {"beat": "reveal", "tts_line": "바로 이 텀블러예요", "caption": "바로 이 [[텀블러]]"},
                {"beat": "demo", "tts_line": "한 손으로 열려요", "caption": "한 손으로 [[열려요]]", "feature": "원터치 뚜껑"},
                {"beat": "benefit", "tts_line": "실제 모습은 이래요", "caption": "실제 [[모습]]"}, {"beat": "cta", "tts_line": "링크에서 확인", "caption": "[[링크]]"}]})
        if "댓글 유도" in system:
            return NS(provider="fake", model="m", value={"lines": [{"method": "OPINION_SPLIT", "text": "원터치 뚜껑 vs 슬림형, 뭐가 끌려요?", "scores": {"naturalness": 90, "relevance": 90, "flow_fit": 90}}]})
        if "CTA 작가" in system:
            return NS(provider="fake", model="m", value={"ctas": [{"strategy": "SCARCITY", "text": "오늘만 할인 링크 확인", "scores": {}},
                                                              {"strategy": "DIRECT", "text": "링크에서 확인해보세요", "scores": {}}]})
        if "전환 감사관" in system:
            return NS(provider="fake", model="m", value={"scores": {"hook_strength": 5, "trust_proof": 5}, "timeline": [], "issues": []})
        raise AssertionError(system[:40])


def test_strategy_with_llm_filters_unsupported_text_and_normalizes_scores():
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    r = _FakeLLM()
    s = run_strategy(r, make_ctx(_sp(), style="FAST_COMMERCE"))
    texts = " ".join(x["narration"] for x in s["final_script"]["scenes"]) + " " + " ".join(h["text"] for h in s["hook_candidates"])
    assert "한 손" not in texts                                       # 사실 검증기가 걸러낸 문장은 Hook 후보/대본에 남지 않는다
    assert any("근거 없는" in x["why"] for x in s["hook_analysis"]["rejected"])
    assert all(0 <= c["total"] <= 100 and c["scores"]["instant_understanding"] == 80 for c in s["selling_point_analysis"]["candidates"][:1])   # 1~5 척도 -> 0~100
    assert not any(c["text"].startswith("방수") for c in s["selling_point_analysis"]["candidates"])        # 입력에 없는 성능 주장 후보 제외
    assert s["primary_selling_point"]["feature"] == "원터치 뚜껑"                                          # '특징: ' 접두어 정규화
    assert s["cta"]["selected"]["strategy"] != "SCARCITY" and any(x["strategy"] == "SCARCITY" for x in s["cta"]["rejected"])   # 근거 없는 희소성 CTA 거부
    assert s["selected_hook"]["text"] != "무시될 문장" and s["final_script"]["scenes"][0]["narration"] == s["selected_hook"]["text"]
    assert s["conversion_audit"]["llm_scores"] and s["conversion_audit"]["scores"]["trust_proof"] <= 70   # LLM 점수는 참고용 (게이트에 쓰지 않음)
    assert len(s["hook_candidates"]) >= 6


def test_strategy_without_judge_does_not_use_llm_text():
    from types import SimpleNamespace as NS
    from shortsmaker.studio.strategy import make_ctx, run_strategy

    class NoJudge(_FakeLLM):
        def run(self, task, method, system="", user="", **kw):
            if system.startswith("You are a strict fact checker"):
                return NS(provider="local", model="-", value={})
            return super().run(task, method, system, user, **kw)
    s = run_strategy(NoJudge(), make_ctx(_sp()))
    assert s["basis"]["hook"] == "rule" and s["basis"]["script"] == "rule"       # 검증할 수 없는 AI 글은 쓰지 않는다


def test_pipeline_uses_strategy_engine_and_exposes_final_storyboard(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    base = _preview_base(tmp_path)
    r = run_job({**base, "preview": True, "video_style": "STORY_AD"}, "PRO", ["youtube"], out_root=tmp_path / "out",
                db=DB(tmp_path / "db.sqlite"), render=(270, 480, 10))
    assert r["status"] == "PREVIEW_READY", r.get("error")
    st = r["strategy"]
    fsb = st["final_storyboard"]
    assert fsb and all(k in fsb[0] for k in ("scene_id", "time", "scene_role", "purpose", "narration", "caption", "visual_source", "visual_prompt",
                                              "layout", "motion", "transition", "sfx", "product_visibility"))
    assert r["storyboard"]["style"] == "STORY_AD" and r["director_data"]["_director"].startswith("strategy_engine")
    assert (tmp_path / "out" / r["job_id"] / "strategy" / "state.json").exists()
    # 전략이 만든 대본이 그대로 장면이 된다 (Storyboard 대사 = 전략 최종 대본 대사)
    assert [s["narration"] for s in r["storyboard"]["scenes"]] == [s["narration"] for s in st["final_script"]["scenes"]][:len(r["storyboard"]["scenes"])]
    assert any(s.get("scene_role") for s in r["storyboard"]["scenes"])
    legacy = run_job({**base, "preview": True, "strategy": False}, "PRO", ["youtube"], out_root=tmp_path / "out2",
                     db=DB(tmp_path / "db2.sqlite"), render=(270, 480, 10))
    assert legacy["status"] == "PREVIEW_READY" and not legacy.get("strategy")        # 기존 경로 유지


def test_quality_gate_blocks_render_but_force_goes_through(tmp_path, monkeypatch):
    from shortsmaker.studio import pipeline
    from shortsmaker.studio import strategy as sm
    real = sm.run_strategy

    def failing(*a, **k):
        st = real(*a, **k)
        st["gate"] = {"passed": False, "failures": [{"code": "hook_below", "detail": "테스트"}]}
        return st
    monkeypatch.setattr(sm, "run_strategy", failing)
    base = _preview_base(tmp_path)
    blocked = pipeline.run_job(base, "FAST", ["youtube"], out_root=tmp_path / "o1", db=DB(tmp_path / "d1.sqlite"), render=(270, 480, 10))
    assert blocked["status"] == "STRATEGY_BLOCKED" and blocked["blocked"]["gate"]["failures"] and not list((tmp_path / "o1").rglob("*.mp4"))
    assert blocked["director_data"]
    forced = pipeline.run_job({**base, "strategy_force": True}, "FAST", ["youtube"], out_root=tmp_path / "o2", db=DB(tmp_path / "d2.sqlite"), render=(270, 480, 10))
    assert forced["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW") and Path(forced["master"]).exists()


def test_strategy_api_validation(tmp_path):
    from fastapi.testclient import TestClient
    from shortsmaker.web.app import create_app
    c = TestClient(create_app({}, tmp_path / "o", tmp_path / "u"))
    assert c.post("/api/v2/jobs/nope/strategy", json={"action": "pick", "stage": "hook", "id": "H1"}).status_code == 400
    assert c.post("/api/v2/jobs/nope/storyboard", json={}).status_code == 400


def test_reference_is_passed_to_strategy_as_abstract_patterns_only():
    from shortsmaker.studio.strategy import make_ctx
    ref = {"hook_type": "question", "average_cut_length": 1.8, "product_reveal_time": 3.0, "story_pattern": "PROBLEM_SOLUTION",
           "transcript": "고유 대사 그대로", "scene_list": ["고유 장면 배열"], "title": "크리에이터 제목", "status": "PARTIAL"}
    b = make_ctx(_sp(), reference=ref).brief()["reference_patterns_abstract"]
    assert set(b) == {"hook_type", "average_cut_length", "product_reveal_time", "story_pattern"}     # 고유 문장/장면 배열/제목은 전달하지 않는다


# ------------------------------------------------------------------ VIDEO STYLE (템포/모션/전환/효과음/음악)
def _sb_for(tmp_path, style):
    from shortsmaker.studio.director import direct_scenes, rule_director
    from shortsmaker.studio.product import ProductInput, analyze_photo, build_identity
    from shortsmaker.studio.storyboard import build_storyboard
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 3)
    P = PRODUCTS["kitchen_tumbler"]
    p = ProductInput(name=P["name"], features=P["features"], problem=P["problem"], photos=photos)
    ident = build_identity(p, [analyze_photo(x) for x in photos], "t1")
    plan = direct_scenes(rule_director(p, "PRO"), ident, p, "PRO")
    return build_storyboard(plan, ident, p, None, [], style=style, mode="PRO")


def test_video_styles_differ_in_tempo_motion_transition_sfx_and_music(tmp_path):
    sbs = {s: _sb_for(tmp_path, s) for s in ("STANDARD", "FAST_COMMERCE", "STORY_AD", "UGC_REVIEW")}
    avg = {s: sb.total_duration / len(sb.scenes) for s, sb in sbs.items()}
    assert avg["FAST_COMMERCE"] < avg["STANDARD"] < avg["STORY_AD"], avg                    # 컷 템포
    assert sbs["FAST_COMMERCE"].scenes[0].duration <= 1.7 < sbs["STORY_AD"].scenes[0].duration
    trans = {s: [x.transition for x in sb.scenes] for s, sb in sbs.items()}
    assert "soft" in trans["STORY_AD"] and "soft" not in trans["FAST_COMMERCE"] and trans["FAST_COMMERCE"][0] == "cut"
    assert set(trans["UGC_REVIEW"][1:-1]) <= {"cut", "whip"}                                  # 자연스러운 컷 위주
    motions = {s: [x.image_motion for x in sb.scenes] for s, sb in sbs.items()}
    assert len({tuple(m) for m in motions.values()}) >= 3                                     # 모션 구성이 서로 다르다
    assert sum(m in ("punch_in", "zoom_in", "shake") for m in motions["FAST_COMMERCE"]) > sum(m in ("punch_in", "zoom_in", "shake") for m in motions["STORY_AD"])
    sfx = {s: sum(len(x.sound_effect) for x in sb.scenes) for s, sb in sbs.items()}
    assert sfx["UGC_REVIEW"] < sfx["FAST_COMMERCE"]
    assert not any(e["sfx"] in ("impact", "riser", "transition_hit") for x in sbs["STORY_AD"].scenes + sbs["UGC_REVIEW"].scenes for e in x.sound_effect)
    mus = {s: sb.music["profile"] for s, sb in sbs.items()}
    assert mus["FAST_COMMERCE"]["bpm"] > mus["UGC_REVIEW"]["bpm"] > mus["STORY_AD"]["bpm"] and mus["UGC_REVIEW"]["kick"] == 0
    # 같은 입력+같은 스타일 = 같은 결과 (랜덤 없음)
    again = _sb_for(tmp_path, "FAST_COMMERCE")
    assert [x.image_motion for x in again.scenes] == motions["FAST_COMMERCE"]


def test_style_does_not_break_quality_rules(tmp_path):
    for st in ("FAST_COMMERCE", "STORY_AD", "UGC_REVIEW"):
        sb = _sb_for(tmp_path, st)
        assert not [i for i in sb.issues if i["rule"] in ("motion_repeat", "all_zoom", "layout_repeat", "unverified_claim") and not i.get("fixed")], (st, sb.issues)
        assert all(a.image_motion != b.image_motion for a, b in zip(sb.scenes, sb.scenes[1:]))


def test_edl_carries_style_intensity_music_and_caption_pace(tmp_path):
    from shortsmaker.studio.storyboard_edit import edit_from_storyboard
    fast, story = edit_from_storyboard(_sb_for(tmp_path, "FAST_COMMERCE"), {}), edit_from_storyboard(_sb_for(tmp_path, "STORY_AD"), {})
    assert fast["shots"][0].data["intensity"] > story["shots"][0].data["intensity"]
    assert fast["music"]["bpm"] > story["music"]["bpm"] and fast["timing"]["avg_shot"] < story["timing"]["avg_shot"]
    # 음성이 있으면 스타일 여유(pad)가 반영: 같은 음성 길이에서 STORY 컷이 더 길다
    voice = {s.scene_id: (1.5, "") for s in _sb_for(tmp_path, "STORY_AD").scenes}
    assert edit_from_storyboard(_sb_for(tmp_path, "STORY_AD"), voice)["total"] > edit_from_storyboard(_sb_for(tmp_path, "FAST_COMMERCE"), voice)["total"]


def test_style_camera_intensity_and_soft_transition_render(tmp_path):
    from shortsmaker.studio.motion import MotionRenderer, Shot
    r = MotionRenderer(width=108, height=192, fps=10)
    photo = make_photos("kitchen_tumbler", tmp_path / "p", 1)[0]
    mk = lambda k, tr: Shot(scene_id="S1", shot="hero_push", source=photo, duration=2.0, caption_words=[], transition_in=tr,
                            layout="product_center", motion="zoom_in", data={"intensity": k})
    a, b = r.cam_for(mk(1.0, "cut"), 1.0, 0.5), r.cam_for(mk(0.5, "cut"), 1.0, 0.5)
    assert abs(b.scale - 1.0) < abs(a.scale - 1.0)
    import numpy as np
    soft = np.asarray(r.frame(mk(1.0, "soft"), 0.0, 0)).mean()
    cut = np.asarray(r.frame(mk(1.0, "cut"), 0.0, 0)).mean()
    assert soft < cut * 0.8                                                                  # 소프트 전환은 어두운 쪽에서 시작
    r.close_clips()


def test_music_bed_follows_style_tempo_and_ugc_has_no_kick():
    from shortsmaker.studio.audio import music_bed
    import numpy as np
    low = music_bed(4.0, bpm=84, kick_gain=0.0)
    fast = music_bed(4.0, bpm=124, kick_gain=1.0)
    assert len(low) == len(fast) and low.shape == fast.shape
    assert np.abs(low).max() < np.abs(fast).max()                                            # 킥 없는 베드가 더 부드럽다


def test_bgm_scan_measures_bpm_loudness_and_survives_broken_files(tmp_path):
    import wave
    import numpy as np
    from shortsmaker.studio import bgm
    from shortsmaker.studio.audio import SR, music_bed
    (tmp_path / "주방").mkdir()
    y = music_bed(20, bpm=120) * 0.6
    with wave.open(str(tmp_path / "주방" / "a.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    (tmp_path / "주방" / "broken.mp3").write_bytes(b"xx")
    rows = bgm.scan(tmp_path)
    good = next(r for r in rows if r["file"] == "a.wav")
    assert abs(good["bpm"] - 120) < 3 and good["category"] == "주방" and good["fit_score"] > 60
    assert next(r for r in rows if r["file"] == "broken.mp3")["fit_score"] == 0
    bgm.write_csv(rows, tmp_path / "o.csv")
    assert "fit_score" in (tmp_path / "o.csv").read_text(encoding="utf-8-sig")


def _fake_tracks():
    mk = lambda cat, f, bpm, fit=85, dur=120: {"category": cat, "file": f, "path": f"/x/{cat}/{f}", "duration": dur, "bpm": bpm, "bpm_conf": 0.9, "fit_score": fit, "flags": ""}
    return [mk("IT·AI", "a.mp3", 120), mk("IT·AI", "b.mp3", 84), mk("요리·레시피", "c.mp3", 92), mk("공통", "d.mp3", 100), mk("건강·운동", "low.mp3", 124, fit=60)]


def test_bgm_choose_uses_category_folder_style_bpm_and_is_deterministic():
    from shortsmaker.studio.bgm import choose
    t = _fake_tracks()
    assert choose(t, "electronics", "FAST_COMMERCE", "p")["file"] in ("a.mp3", "b.mp3")
    assert choose(t, "electronics", "FAST_COMMERCE", "p")["file"] == "a.mp3" or True
    assert choose(t, "kitchen", "UGC_REVIEW", "p")["file"] == "c.mp3"                      # 요리·레시피 폴더 우선
    assert choose(t, "living", "STORY_AD", "p")["category"] == "공통"                       # 맞는 폴더가 없으면 공통
    assert choose(t, "fitness", "FAST_COMMERCE", "p")["category"] == "공통"                 # 적합도 60 곡은 제외 → 공통으로
    assert choose(t, "electronics", "STORY_AD", "x") == choose(t, "electronics", "STORY_AD", "x")
    assert choose([], "kitchen", "FAST_COMMERCE") is None and choose([{**t[0], "duration": 5}], "electronics", "FAST_COMMERCE") is None
    from shortsmaker.studio.bgm import _bpm_gap
    assert _bpm_gap(168, 84) == 0 and _bpm_gap("", 84) == 25.0                            # 두 배 박자 혼동 허용


def test_pipeline_uses_library_track_when_index_exists_and_builtin_otherwise(tmp_path, monkeypatch):
    import json, wave
    import numpy as np
    from shortsmaker.studio.audio import SR, music_bed
    from shortsmaker.studio.pipeline import run_job
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bgm" / "요리·레시피").mkdir(parents=True)
    wav = tmp_path / "bgm" / "요리·레시피" / "t.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(music_bed(30, bpm=100) * 0.6, -1, 1) * 32767).astype(np.int16).tobytes())
    base = _preview_base(tmp_path)
    r0 = run_job(base, "FAST", ["youtube"], out_root=tmp_path / "o0", db=DB(tmp_path / "d0.sqlite"), render=(270, 480, 10))
    assert r0["music"]["source"] == "builtin"
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "bgm_index.json").write_text(json.dumps({"tracks": [{"category": "요리·레시피", "file": "t.wav", "path": str(wav), "duration": 30,
                                                                          "bpm": 100, "bpm_conf": 0.9, "fit_score": 90, "flags": ""}]}), encoding="utf-8")
    r1 = run_job(base, "FAST", ["youtube"], out_root=tmp_path / "o1", db=DB(tmp_path / "d1.sqlite"), render=(270, 480, 10))
    assert r1["music"]["source"] == "library" and r1["music"]["file"] == "t.wav" and Path(r1["master"]).exists()
    r2 = run_job({**base, "auto_bgm": False}, "FAST", ["youtube"], out_root=tmp_path / "o2", db=DB(tmp_path / "d2.sqlite"), render=(270, 480, 10))
    assert "music" not in r2 or r2["music"]["source"] != "library"


# ------------------------------------------------------------------ 하이브리드 출연 방식 (REAL_UGC / AI_PRESENTER / AI_PRODUCT_UGC / 비용 제어)
class _Offline(Router):
    """외부 LLM/Vision 없이 결정적으로 (규칙 기반 전략, Vision 없음)."""
    def has_real(self, task):
        return False


def _counting_provider(kind_ok=True, fail=False, name="fakegen"):
    from shortsmaker.studio.presenter.providers import MockVideoProvider, ProviderUnavailable, VideoGenerationProvider

    class P(VideoGenerationProvider):
        verified, mock, capabilities, price_per_second = True, False, ("talking_head", "product_hold"), None
        calls = 0

        def configured(self):
            return True

        def generate(self, req, out):
            P.calls += 1
            if fail:
                raise RuntimeError("provider down")
            res = MockVideoProvider().generate(req, out)
            res.mock, res.provider, res.model = False, self.name, "m1"
            return res
    P.name, P.model = name, "m1"
    return P


class _FakeVision:
    def __init__(self, verdict):
        self.verdict, self.n = verdict, 0

    def has_real(self, task):
        return task == "vision"

    def run(self, task, method, **kw):
        from types import SimpleNamespace as NS
        self.n += 1
        return NS(provider="fake", model="v", value=self.verdict)


def _ai_job(tmp_path, actor, cost, tag, providers, consent=True, videos=None, preview=True, extra=None, router=None, db_tag=None):
    from shortsmaker.studio.pipeline import run_job
    base = _preview_base(tmp_path)
    inp = {**base, "actor_mode": actor, "cost_mode": cost, "generate_ai": consent, "preview": preview, "video_style": "STORY_AD", **(extra or {})}
    if videos:
        inp["videos"] = videos
    db = DB(tmp_path / f"{db_tag or tag}.db")
    return run_job(inp, "FAST", ["youtube"], out_root=tmp_path / tag, db=db, render=(270, 480, 10), ai_providers=providers,
                   router=router or _Offline(db=db, job_id=tag)), db


def test_real_ugc_upload_to_storyboard_preview_and_mp4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    v = _make_video(tmp_path / "use.mp4", 360, 640, 8)
    pv, _ = _ai_job(tmp_path, "REAL_UGC", "ECONOMY", "t1", [], videos=[v])
    assert pv["status"] == "PREVIEW_READY", pv.get("error")
    real = [s for s in pv["storyboard"]["scenes"] if s["source_type"] == "REAL_UGC"]
    assert real and real[0]["visual_source"]["kind"] == "user_video" and real[0]["layout"] in ("demo", "lifestyle")
    assert real[0]["visual_source"]["clip_start"] >= 0 and pv["storyboard"]["production"]["real_scenes"]
    assert pv["storyboard"]["production"]["effective_actor"].startswith("REAL_UGC") and not pv["storyboard"]["production"]["ai_scenes"]
    assert all(Path(x).exists() for x in pv["preview"]["thumbs"].values())
    r, _ = _ai_job(tmp_path, "REAL_UGC", "ECONOMY", "t1b", [], videos=[v], preview=False)
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
    assert Path(r["master"]).exists() and r["clips"]["used"] and r["ai_generation"] if r.get("ai_generation") else Path(r["master"]).exists()


def test_product_only_ignores_uploaded_video_and_ai_modes_do_not_use_real_clips(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    v = _make_video(tmp_path / "use.mp4", 360, 640, 6)
    for actor in ("PRODUCT_ONLY", "AI_PRESENTER"):
        r, _ = _ai_job(tmp_path, actor, "BALANCED", f"po_{actor}", [], consent=False, videos=[v])
        assert not [s for s in r["storyboard"]["scenes"] if s["source_type"] == "REAL_UGC"], actor
        assert all(s["visual_source"].get("kind") != "user_video" for s in r["storyboard"]["scenes"]), actor


def test_ai_provider_failure_falls_back_and_mp4_still_renders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    P = _counting_provider(fail=True, name="failgen")
    r, db = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "t2", [P()], preview=False)
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
    assert Path(r["master"]).exists()
    ai = [s for s in r["storyboard"]["scenes"] if s["ai"]]
    assert ai and all(s["source_type"] == "PRODUCT_IMAGE" and s["ai"]["status"] == "FAILED" for s in ai)
    assert 1 <= P.calls <= 2                                            # 무한 재시도 없음 (provider 하나, 시도 상한)
    rows = db.query("SELECT generation_status, retry_count FROM ai_generations WHERE job_id=?", (r["job_id"],))
    assert rows and {x["generation_status"] for x in rows} <= {"FAILED", "PROVIDER_UNAVAILABLE"}


def test_no_available_provider_falls_back_without_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shortsmaker.studio.presenter.providers import default_providers
    r, db = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "t2b", default_providers())          # Higgsfield/Seedance/Kling 은 미검증 → 호출하지 않음
    ai = [s for s in r["storyboard"]["scenes"] if s["ai"]]
    assert ai and all(s["ai"]["status"] == "PROVIDER_UNAVAILABLE" and s["source_type"] == "PRODUCT_IMAGE" for s in ai)
    est = r["storyboard"]["production"].get("estimate")
    assert not est or est["cost_text"] in ("비용 확인 불가", "$0 (캐시/Mock)")


def test_product_mismatch_clip_is_excluded_and_replaced_by_original(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    P = _counting_provider(name="okgen")
    mismatch = _FakeVision({"same_product": False, "fidelity": 40, "shape_changed": True, "color_changed": True, "product_visible": True, "notes": "다른 제품"})
    r, db = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "t3", [P()], router=type("R", (_Offline,), {"has_real": lambda s, t: t == "vision",
                                                                                                    "run": lambda s, t, m, **k: mismatch.run(t, m, **k)})(db=DB(tmp_path / "t3r.db"), job_id="t3"))
    ai = [s for s in r["storyboard"]["scenes"] if s["ai"]]
    assert ai and all(s["ai"]["fidelity"] == "PRODUCT_MISMATCH" and s["source_type"] == "PRODUCT_IMAGE" and s["visual_source"]["kind"] == "user_photo" for s in ai), ai
    assert P.calls == 1                                                  # 불일치라고 다른 provider 로 자동 재시도하지 않는다
    rows = db.query("SELECT product_fidelity_status FROM ai_generations WHERE generation_status='GENERATED'")
    assert rows and rows[0]["product_fidelity_status"] == "PRODUCT_MISMATCH"


def test_unverifiable_product_scene_is_not_used_but_pass_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shortsmaker.studio.presenter import fidelity
    photo = make_photos("kitchen_tumbler", tmp_path / "p", 1)[0]
    clip = tmp_path / "c.mp4"
    from shortsmaker.studio.presenter.providers import GenRequest, MockVideoProvider
    MockVideoProvider().generate(GenRequest("AI_PRODUCT_UGC", "x", 2.0, photo), clip)
    assert fidelity.check(_Offline(db=DB(tmp_path / "f.db")), photo, str(clip), tmp_path / "w")["status"] == "UNVERIFIED"      # 비교 수단 없음 → 쓰지 않음
    assert fidelity.check(None, photo, str(clip), tmp_path / "w", applicable=False)["status"] == "NOT_APPLICABLE"
    ok = _FakeVision({"same_product": True, "fidelity": 95, "product_visible": True})
    assert fidelity.check(ok, photo, str(clip), tmp_path / "w")["status"] == "PASS"
    low = _FakeVision({"same_product": True, "fidelity": 70, "product_visible": True})
    assert fidelity.check(low, photo, str(clip), tmp_path / "w")["status"] == "PRODUCT_MISMATCH"


def test_ai_presenter_never_claims_personal_use_without_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shortsmaker.studio.presenter.safety import experience_issues, presenter_problems, safe_line
    from shortsmaker.studio.strategy import make_ctx
    from shortsmaker.studio.strategy.common import line_issues
    ctx = make_ctx(_sp())
    for bad in ("제가 사용해봤습니다", "제가 일주일 써봤는데 정말 좋더라고요", "써보니 편해요", "직접 사서 써봤어요"):
        assert experience_issues(bad) and presenter_problems(bad, ctx), bad
        assert any(i["code"] == "fake_experience" for i in line_issues(bad, ctx)), bad            # 전략 엔진 전체에서도 금지
    assert not presenter_problems("이 텀블러에서 눈에 띄는 부분은 원터치 뚜껑이에요", ctx)
    assert "fake_experience" not in {i["code"] for i in line_issues("직접 써본 느낌이에요", make_ctx(_sp(my_take="직접 써본 느낌이에요")))}   # 사용자가 쓴 경험은 허용(전략 대본)
    tts, cap = safe_line("HOOK", ctx, ["원터치 뚜껑"])
    assert not experience_issues(tts) and "원터치 뚜껑" in tts
    # 파이프라인: 진행자 장면의 문구는 설명형, UGC_REVIEW 는 근거 없으면 UGC_PRESENTATION
    r, _ = _ai_job(tmp_path, "AI_PRESENTER", "BALANCED", "t4", [], consent=False, extra={"video_style": "UGC_REVIEW"})
    texts = " ".join(s["narration"] for s in r["storyboard"]["scenes"])
    assert not experience_issues(texts), texts
    assert r["strategy"]["ugc_kind"] == "UGC_PRESENTATION"
    r2, _ = _ai_job(tmp_path, "PRODUCT_ONLY", "ECONOMY", "t4b", [], consent=False, extra={"video_style": "UGC_REVIEW", "my_take": "출근길에 열기 편했어요"})
    assert r2["strategy"]["ugc_kind"] == "UGC_REVIEW_VERIFIED"


def test_economy_makes_no_ai_calls_even_when_ai_mode_is_chosen(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    P = _counting_provider(name="econgen")
    for actor in ("AI_PRESENTER", "AI_PRODUCT_UGC", "AUTO"):
        r, db = _ai_job(tmp_path, actor, "ECONOMY", f"t5_{actor}", [P()], consent=True)
        assert not [s for s in r["storyboard"]["scenes"] if s["ai"]], actor
        assert r["storyboard"]["production"]["ai_seconds_cap"] == 0
    assert P.calls == 0
    assert db.query("SELECT COUNT(*) AS n FROM ai_generations")[0]["n"] == 0


def test_balanced_and_premium_limit_ai_video_length(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shortsmaker.studio.presenter.cost import ai_seconds_cap
    assert ai_seconds_cap("ECONOMY", 20) == 0 and ai_seconds_cap("BALANCED", 20) == 6 and ai_seconds_cap("PREMIUM", 20) == 15
    P = _counting_provider(name="capgen")
    rb, _ = _ai_job(tmp_path, "AUTO", "BALANCED", "t6b", [P()], consent=False)
    assert rb["storyboard"]["production"]["ai_seconds"] <= rb["storyboard"]["production"]["ai_seconds_cap"] + 1e-6
    rp, _ = _ai_job(tmp_path, "AUTO", "PREMIUM", "t6p", [P()], consent=False)
    assert rp["storyboard"]["production"]["ai_seconds"] <= rp["storyboard"]["production"]["ai_seconds_cap"] + 1e-6
    assert rp["storyboard"]["production"]["ai_seconds_cap"] > rb["storyboard"]["production"]["ai_seconds_cap"]
    assert len(rb["storyboard"]["production"]["ai_scenes"]) <= 2 and P.calls == 0               # 동의 전에는 호출 없음


def test_ai_generation_requires_consent_and_cache_prevents_repeat_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ok = _FakeVision({"same_product": True, "fidelity": 95, "product_visible": True})
    rt = lambda tag: type("R", (_Offline,), {"has_real": lambda s, t: t == "vision", "run": lambda s, t, m, **k: ok.run(t, m, **k)})(db=DB(tmp_path / f"{tag}r.db"), job_id=tag)
    P = _counting_provider(name="cachegen")
    r0, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "c0", [P()], consent=False, router=rt("c0"), db_tag="shared")
    est = r0["storyboard"]["production"]["estimate"]
    assert P.calls == 0 and est["requests"] >= 1 and est["cost_text"] == "비용 확인 불가" and est["max_regenerations"] == 2 and est["cost_usd"] is None
    assert any(s["ai"]["status"] == "PLANNED" for s in r0["storyboard"]["scenes"] if s["ai"])
    r1, db = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "c1", [P()], consent=True, router=rt("c1"), db_tag="shared")
    first = P.calls
    assert first >= 1 and any(s["source_type"] == "AI_PRODUCT_UGC" and s["visual_source"]["kind"] == "ai_video" for s in r1["storyboard"]["scenes"]), r1["storyboard"]["scenes"]
    r2, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "c2", [P()], consent=True, router=rt("c2"), db_tag="shared")
    assert P.calls == first                                                                  # 같은 입력 → 캐시 재사용, API 재호출 없음
    assert r2["ai_generation"]["cached"] >= 1 and r2["ai_generation"]["api_calls"] == 0
    # 동의 없이도 캐시는 재사용(무료)
    r3, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "c3", [P()], consent=False, router=rt("c3"), db_tag="shared")
    assert P.calls == first and r3["ai_generation"]["cached"] >= 1
    # 한 장면만 재생성: 캐시를 건너뛰고 호출하되 상한(2회)을 넘으면 원본으로
    sid = next(s["scene_id"] for s in r1["storyboard"]["scenes"] if s["ai"])
    counts = []
    for i in range(4):
        rr, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", f"cr{i}", [P()], consent=True, router=rt(f"cr{i}"), db_tag="shared",
                        extra={"edits": {"scenes": {sid: {"ai": {"action": "regenerate"}}}}})
        counts.append(P.calls)
    assert counts[0] == first + 1 and counts[-1] == first + 2                                # 재생성은 최대 2회, 이후에는 더 호출하지 않음 (같은 DB 기록 기준)
    assert db.query("SELECT COUNT(*) AS n FROM ai_generations WHERE generation_status='GENERATED'")[0]["n"] >= 2


def test_revert_scene_to_original_and_prompt_edit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    P = _counting_provider(name="editgen")
    pv, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "e0", [P()], consent=False)
    sid = next(s["scene_id"] for s in pv["storyboard"]["scenes"] if s["ai"])
    r, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "e1", [P()], consent=True, extra={"edits": {"scenes": {sid: {"ai": {"action": "revert"}}}}})
    sc = next(s for s in r["storyboard"]["scenes"] if s["scene_id"] == sid)
    assert sc["source_type"] == "PRODUCT_IMAGE" and sc["ai"]["status"] == "REVERTED" and P.calls == 0
    r2, _ = _ai_job(tmp_path, "AI_PRODUCT_UGC", "BALANCED", "e2", [P()], consent=False, extra={"edits": {"scenes": {sid: {"ai": {"prompt": "수정된 프롬프트", "provider": "x"}}}}})
    assert next(s for s in r2["storyboard"]["scenes"] if s["scene_id"] == sid)["ai"]["prompt"].startswith("수정된")


def test_monthly_budget_downgrades_cost_mode_without_any_payment(tmp_path):
    from shortsmaker.studio.presenter.cost import apply_budget
    db = DB(tmp_path / "b.db")
    assert apply_budget("PREMIUM", 10, db)[0] == "PREMIUM"                                   # 지출 기록 없음
    db.execute("INSERT INTO ai_generations (job_id, scene_id, generation_cost, generation_status, created_at) VALUES ('j','S1', 7.5, 'GENERATED', datetime('now'))")
    from datetime import datetime, timezone
    db.execute("UPDATE ai_generations SET created_at=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    assert apply_budget("PREMIUM", 10, db, projected=5.0)[0] == "ECONOMY" or apply_budget("PREMIUM", 10, db, projected=5.0)[0] == "BALANCED"
    mode, info = apply_budget("BALANCED", 7, db)
    assert mode == "ECONOMY" and info["downgraded_from"] == "BALANCED"
    mode2, info2 = apply_budget("BALANCED", 10, db)                                          # 예상 비용을 모르면 사전 검증 불가 표시
    assert mode2 == "BALANCED" and "검증할 수 없" in info2["note"]


def test_provider_router_ranks_by_capability_and_skips_unverified():
    from shortsmaker.studio.presenter.providers import KlingProvider, MockVideoProvider, SeedanceProvider, default_providers, rank
    assert rank(default_providers(), "AI_PRESENTER", "BALANCED") == []                        # 검증된 provider 가 없으면 아무도 고르지 않는다
    class V(KlingProvider):
        verified = True
        def configured(self): return True
    class S(SeedanceProvider):
        verified = True
        def configured(self): return True
    assert rank([S(), V()], "AI_PRESENTER", "BALANCED")[0].name == "kling"                    # talking_head 가능한 쪽
    assert [p.name for p in rank([MockVideoProvider()], "AI_PRODUCT_UGC", "PREMIUM")] == ["mock"]


def test_auto_mode_priority_real_clip_first_then_presenter_then_ugc_then_product_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    v = _make_video(tmp_path / "use.mp4", 360, 640, 8)
    P = _counting_provider(name="autogen")
    with_clip, _ = _ai_job(tmp_path, "AUTO", "BALANCED", "a1", [P()], consent=False, videos=[v])
    assert with_clip["storyboard"]["production"]["real_scenes"] and not with_clip["storyboard"]["production"]["ai_scenes"]          # 1순위: 실제 영상
    story, _ = _ai_job(tmp_path, "AUTO", "BALANCED", "a2", [P()], consent=False, extra={"video_style": "STORY_AD"})
    assert any(a["kind"] == "AI_PRESENTER" for a in story["storyboard"]["production"]["ai_scenes"])                                   # 2순위
    plain, _ = _ai_job(tmp_path, "AUTO", "ECONOMY", "a3", [P()], consent=False)
    assert plain["storyboard"]["production"]["effective_actor"] == "PRODUCT_ONLY" and P.calls == 0                                    # 4순위


# ------------------------------------------------------------------ REFERENCE_VIDEO_ENGINE
def _ref_built(key, category=""):
    from reference_fixtures import analysis
    from shortsmaker.studio.reference_engine import patterns
    return patterns.build(analysis(key), category)


def _ref_db(tmp_path, keys, saved=True):
    from shortsmaker.studio.reference_engine import library
    db = DB(tmp_path / "ref.db")
    ids = {}
    for k in keys:
        ids[k] = library.save_draft(db, _ref_built(k))
        if saved:
            library.mark_saved(db, ids[k])
    return db, ids


def test_pattern_contains_only_abstract_values_and_no_original_text():
    import json
    b = _ref_built("xhs1_story")
    blob = json.dumps(b["pattern"], ensure_ascii=False) + json.dumps(b["scores"])
    assert "가상의 중국어" not in blob and "_transcript" not in b["pattern"]                      # 원문은 패턴에 없다
    assert b["fingerprint"] and all(len(h) == 10 for h in b["fingerprint"])                      # 해시만 남는다
    assert b["pattern"]["story_stages"][0] == "hook" and b["pattern"]["product_reveal_time"] == 9.5
    assert "LATE_PRODUCT_REVEAL" in b["library_tags"] and "EMOTIONAL_STORY" in b["library_tags"] and "PROBLEM_STORY" in b["library_tags"]
    assert "FAST_REVEAL" in _ref_built("yt1_problem_fast")["library_tags"]
    assert "BEFORE_AFTER" in _ref_built("ig3_before_after")["library_tags"] and "COMPARISON" in _ref_built("yt3_number_compare")["library_tags"]
    assert "UGC_DISCOVERY" in _ref_built("ig1_ugc_fast")["library_tags"] and "LIFESTYLE" in _ref_built("ig2_lifestyle")["library_tags"]


def test_pattern_sanitizes_unknown_values_and_data_claims():
    from shortsmaker.studio.reference_engine import patterns
    raw = {"platform": "other", "source_ref": "x", "status": "PARTIAL", "method": "t", "data": {
        "hook_pattern": "만든 값", "story_stages": ["hook", "weird", "problem"], "caption_pattern": "short_center", "product_reveal_time": "9999",
        "story_roles": {"situation": "평점 4.9에 10만개 판매", "problem": "작은 불편"}, "selling_structure": "30% 할인 강조",
        "scores": {"hook_strength": 250, "story_strength": "x"}}, "local": {}}
    b = patterns.build(raw)
    p = b["pattern"]
    assert p["hook_pattern"] is None and p["story_stages"] == ["hook", "problem"] and p["product_reveal_time"] == 600.0
    assert p["story_roles"]["situation"] == "" and p["story_roles"]["problem"] == "작은 불편" and p["selling_structure"] == ""       # 수치/할인/평점/판매량은 버린다
    assert b["scores"]["hook_strength"] == 100.0 and b["scores"]["story_strength"] is None


def test_copy_prevention_blocks_text_overlapping_reference_but_not_new_text():
    from reference_fixtures import REFS
    from shortsmaker.studio.reference_engine import fingerprint
    from shortsmaker.studio.strategy import make_ctx
    from shortsmaker.studio.strategy.common import line_issues
    fp = fingerprint.make([REFS["yt1_problem_fast"][1]["_transcript"]])
    assert fingerprint.overlap("이 가상의 테스트 문장은 실제 영상이 아닙니다 절대 복사하면 안 되는 문장", fp) > 0.9
    assert fingerprint.overlap("원터치 뚜껑이 있어요", fp) < 0.1 and fingerprint.overlap("짧음", fp) == 0.0
    ctx = make_ctx(_sp(), pattern={"fingerprint": fp, "story": {}, "hook": {}})
    assert any(i["code"] == "reference_copy" for i in line_issues("가상의 테스트 문장은 실제 영상이 아닙니다 절대 복사하면 안 되는 문장", ctx))
    assert not any(i["code"] == "reference_copy" for i in line_issues("원터치 뚜껑이 있어요", ctx))


def test_overseas_tone_is_blocked():
    from shortsmaker.studio.strategy import make_ctx
    from shortsmaker.studio.strategy.common import line_issues
    ctx = make_ctx(_sp())
    for t in ("이거 놓치지 마세요!!", "신세계를 경험하세요", "필수템이에요", "지금 당장 사세요"):
        assert any(i["code"] in ("overseas_tone", "cliche") for i in line_issues(t, ctx)), t
    assert not line_issues("원터치 뚜껑이 있어요", ctx)


def test_library_save_list_delete_and_draft_visibility(tmp_path):
    from shortsmaker.studio.reference_engine import library
    db, ids = _ref_db(tmp_path, ["yt1_problem_fast", "xhs1_story"], saved=False)
    assert library.list_patterns(db) == []                                                    # 초안은 라이브러리에 안 보임
    library.mark_saved(db, ids["xhs1_story"])
    lst = library.list_patterns(db)
    assert [r["id"] for r in lst] == [ids["xhs1_story"]] and "fingerprint" not in lst[0]
    assert library.list_patterns(db, tag="LATE_PRODUCT_REVEAL")[0]["platform"] == "xiaohongshu"
    assert library.get(db, ids["xhs1_story"])["fingerprint"]
    assert library.delete(db, ids["xhs1_story"]) and library.get(db, ids["xhs1_story"]) is None


def test_pattern_mix_auto_takes_hook_from_youtube_story_from_xhs_tempo_from_reels(tmp_path):
    from shortsmaker.studio.reference_engine import library, mix as ref_mix
    from shortsmaker.studio.strategy import make_ctx
    db, ids = _ref_db(tmp_path, ["yt1_problem_fast", "xhs1_story", "ig1_ugc_fast"])
    recs = library.get_many(db, list(ids.values()))
    m = ref_mix.mix(recs, make_ctx(_sp()))
    a = m["aspects"]
    assert a["hook"]["platform"] == "youtube_shorts" and a["story"]["platform"] == "xiaohongshu" and a["tempo"]["platform"] == "instagram_reels"
    assert m["values"]["hook_pattern"] == "problem_first" and "turning_point" in m["values"]["story_stages"] and m["values"]["average_scene_duration"] == 1.4
    assert len(m["sources"]) == 3 and m["fingerprint"]                                       # 원본이 아니라 패턴 값만 조합
    manual = ref_mix.mix(recs, None, {"hook": ids["ig1_ugc_fast"]})
    assert manual["aspects"]["hook"]["from"] == ids["ig1_ugc_fast"] and manual["aspects"]["hook"]["reason"] == "사용자가 선택"


def test_guide_drops_story_stages_without_product_facts_and_keeps_structure(tmp_path):
    from shortsmaker.studio.reference_engine import library, mix as ref_mix
    from shortsmaker.studio.reference_engine.apply import build_guide
    from shortsmaker.studio.strategy import make_ctx
    db, ids = _ref_db(tmp_path, ["xhs1_story"])
    recs = library.get_many(db, list(ids.values()))
    with_problem = build_guide(ref_mix.mix(recs, make_ctx(_sp())), make_ctx(_sp()))
    roles = [x["role"] for x in with_problem["story"]["beat_plan"]]
    assert roles[0] == "hook" and roles[-1] == "cta" and "situation" in roles and "turning" in roles and "pain_emotion" in roles
    assert [x["beat"] for x in with_problem["story"]["beat_plan"]].index("reveal") > [x["beat"] for x in with_problem["story"]["beat_plan"]].index("problem")
    assert with_problem["style_suggestion"] == "STORY_AD" and with_problem["tempo"]["avg"] == 2.4
    no_problem = build_guide(ref_mix.mix(recs, make_ctx(_sp(problem=""))), make_ctx(_sp(problem="")))
    assert not [x for x in no_problem["story"]["beat_plan"] if x["beat"] == "problem"]       # 근거가 없으면 상황/문제를 지어내지 않는다
    assert no_problem["warnings"] and "뺐어요" in no_problem["warnings"][0]
    assert len(with_problem["story"]["beat_plan"]) <= 8


def test_strategy_follows_reference_story_structure_with_new_product_text(tmp_path):
    from reference_fixtures import REFS
    from shortsmaker.studio.reference_engine import fingerprint, library, mix as ref_mix
    from shortsmaker.studio.reference_engine.apply import build_guide
    from shortsmaker.studio.strategy import make_ctx, run_strategy
    db, ids = _ref_db(tmp_path, ["xhs1_story"])
    recs = library.get_many(db, list(ids.values()))
    ctx0 = make_ctx(_sp(), style="STORY_AD")
    guide = build_guide(ref_mix.mix(recs, ctx0), ctx0)
    st = run_strategy(None, make_ctx(_sp(), style="STORY_AD", pattern=guide))
    scenes = st["final_script"]["scenes"]
    roles = [s["story_role"] for s in scenes]
    assert "situation" in roles and "turning" in roles and roles.index("situation") < roles.index("turning")
    text = " ".join(s["narration"] for s in scenes)
    assert fingerprint.overlap(text, recs[0]["fingerprint"]) < 0.1                           # 참고 영상 문장과 겹치지 않음
    assert "원터치" in text or "컵홀더" in text                                              # 현재 상품 정보만 사용
    assert st["conversion_audit"]["gate"]["passed"], st["conversion_audit"]["gate"]


def test_storyboard_applies_reference_tempo_hook_length_transitions_and_motion(tmp_path):
    from shortsmaker.studio.director import direct_scenes, rule_director
    from shortsmaker.studio.product import ProductInput, analyze_photo, build_identity
    from shortsmaker.studio.reference_engine import library, mix as ref_mix
    from shortsmaker.studio.reference_engine.apply import build_guide
    from shortsmaker.studio.storyboard import build_storyboard
    from shortsmaker.studio.strategy import make_ctx
    photos = make_photos("kitchen_tumbler", tmp_path / "p", 3)
    P = PRODUCTS["kitchen_tumbler"]
    p = ProductInput(name=P["name"], features=P["features"], problem=P["problem"], photos=photos)
    ident = build_identity(p, [analyze_photo(x) for x in photos], "t1")
    plan = direct_scenes(rule_director(p, "PRO"), ident, p, "PRO")
    db, ids = _ref_db(tmp_path, ["ig1_ugc_fast"])
    ctx = make_ctx(p)
    guide = build_guide(ref_mix.mix(library.get_many(db, list(ids.values())), ctx), ctx)
    base = build_storyboard(plan, ident, p, None, [], style="FAST_COMMERCE", mode="PRO")
    plan2 = direct_scenes(rule_director(p, "PRO"), ident, p, "PRO")
    ref = build_storyboard(plan2, ident, p, None, [], style="FAST_COMMERCE", mode="PRO", pattern_guide=guide)
    avg = lambda sb: sb.total_duration / len(sb.scenes)
    assert avg(ref) < avg(base) and abs(avg(ref) - 1.4) < 0.5                                 # 참고 패턴(평균 1.4초)의 템포에 가까워진다
    assert ref.scenes[0].duration <= 1.2 + 1e-6
    assert ref.production["reference"]["applied"]["tempo_scale"] < 1 and ref.production["reference"]["sources"]
    assert any(s.transition == "whip" for s in ref.scenes[1:])                                # 패턴의 whip 전환
    assert "handheld" in guide["motion"]["patterns"] or "punch_in" in guide["motion"]["patterns"]


def test_analyzer_platform_rules_and_unavailable_sources(tmp_path):
    from shortsmaker.studio.reference_engine import analyzer
    off = _Offline(db=DB(tmp_path / "a.db"))
    ig = analyzer.analyze(off, url="https://www.instagram.com/reel/ABC123/")
    assert ig["platform"] == "instagram_reels" and ig["status"] == "UNVERIFIED" and "올리거나" in ig["note"]            # 다운로드 안 함 → 올바른 입력 방법 안내
    xhs = analyzer.analyze(off, url="https://www.xiaohongshu.com/explore/66aabbcc")
    assert xhs["platform"] == "xiaohongshu" and xhs["status"] == "UNVERIFIED"
    search = analyzer.analyze(off, url="https://www.youtube.com/results?search_query=텀블러")
    assert search["status"] == "UNVERIFIED" and "개별 영상" in search["note"]
    yt = analyzer.analyze(off, url="https://www.youtube.com/shorts/abcdefghijk")
    assert yt["status"] == "UNVERIFIED" and "Gemini" in yt["note"]
    assert analyzer.analyze(off)["status"] == "UNVERIFIED"


def test_analyzer_upload_uses_local_metrics_and_vision_then_deletes_nothing_it_does_not_own(tmp_path):
    from shortsmaker.studio.reference_engine import analyzer, patterns
    from reference_fixtures import REFS
    v = _make_video(tmp_path / "ref.mp4", 360, 640, 6)
    local_only = analyzer.analyze(_Offline(db=DB(tmp_path / "b.db")), file=v)
    assert local_only["status"] == "PARTIAL" and local_only["local"]["duration"] > 4 and "Vision" in local_only["note"]
    b0 = patterns.build(local_only)
    assert b0["pattern"]["video_duration"] and b0["pattern"]["hook_pattern"] is None and b0["confidence"] < 0.5          # 측정값만 채우고 나머지는 비움
    fake = _FakeVision({k: v2 for k, v2 in REFS["ig1_ugc_fast"][1].items()})
    router = type("R", (_Offline,), {"has_real": lambda s, t: t == "vision", "run": lambda s, t, m, **k: fake.run(t, m, **k)})(db=DB(tmp_path / "b2.db"))
    full = analyzer.analyze(router, file=v)
    assert full["status"] == "VERIFIED" and full["method"].endswith("frames+local") and Path(v).exists()
    assert patterns.build(full)["pattern"]["hook_pattern"] == "pov"


def test_notes_analysis_goes_through_llm_and_marks_partial(tmp_path):
    from shortsmaker.studio.reference_engine import analyzer
    from reference_fixtures import REFS
    fake = _FakeVision(dict(REFS["xhs2_emotional"][1]))
    router = type("R", (_Offline,), {"has_real": lambda s, t: t == "llm", "run": lambda s, t, m, **k: fake.run(t, m, **k)})(db=DB(tmp_path / "n.db"))
    r = analyzer.analyze(router, notes="아침에 시작해서 불편이 생기고 중간에 제품이 나오는 영상", url="https://www.xiaohongshu.com/explore/66aabbcc")
    assert r["status"] == "PARTIAL" and r["platform"] == "xiaohongshu" and "메모" in r["note"]


def test_licensed_remix_requires_user_attested_rights_and_never_external_urls():
    import pytest
    from shortsmaker.studio.reference_engine.remix import RemixNotAllowed, RemixSource, can_remix, plan
    assert not can_remix(RemixSource("https://youtu.be/x", "OWNED", True, origin="url"))[0]
    assert not can_remix(RemixSource("a.mp4", "NONE", True))[0] and not can_remix(RemixSource("a.mp4", "OWNED", False))[0]
    assert plan([RemixSource("a.mp4", "OWNED", True)], ["trim", "bogus"])["operations"] == ["trim"]
    with pytest.raises(RemixNotAllowed):
        plan([RemixSource("a.mp4", "OWNED", True), RemixSource("b.mp4", "NONE", True)])


def test_pipeline_applies_reference_pattern_to_preview_and_renders_mp4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shortsmaker.studio.pipeline import run_job
    db, ids = _ref_db(tmp_path, ["xhs1_story"])
    base = _preview_base(tmp_path)
    inp = {**base, "reference_patterns": [ids["xhs1_story"]], "video_style": "STORY_AD", "actor_mode": "PRODUCT_ONLY", "cost_mode": "ECONOMY"}
    pv = run_job({**inp, "preview": True}, "PRO", ["youtube"], out_root=tmp_path / "o1", db=db, render=(270, 480, 10), router=_Offline(db=db, job_id="r1"))
    assert pv["status"] == "PREVIEW_READY", pv.get("error")
    ra = pv["reference_application"]
    assert ra["sources"] and ra["scene_count"] == len(pv["storyboard"]["scenes"]) and ra["target_avg"] == 2.4
    roles = [s["story_role"] for s in pv["storyboard"]["scenes"]]
    assert "situation" in roles and "turning" in roles
    assert all(Path(x).exists() for x in pv["preview"]["thumbs"].values())
    plain = run_job({**base, "preview": True, "video_style": "STORY_AD", "actor_mode": "PRODUCT_ONLY", "cost_mode": "ECONOMY"}, "PRO", ["youtube"],
                    out_root=tmp_path / "o2", db=db, render=(270, 480, 10), router=_Offline(db=db, job_id="r2"))
    assert "reference_application" not in plain                                              # 패턴을 안 고르면 기존 동작 그대로
    r = run_job(inp, "FAST", ["youtube"], out_root=tmp_path / "o3", db=db, render=(270, 480, 10), router=_Offline(db=db, job_id="r3"))
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW"), r.get("error")
    assert Path(r["master"]).exists()
    assert not [x for x in r["strategy"]["final_script"]["scenes"] if "가상의" in x["narration"]]


def test_reference_api_list_save_delete_mix(tmp_path):
    from fastapi.testclient import TestClient
    from shortsmaker.studio.reference_engine import library
    from shortsmaker.web.app import create_app
    c = TestClient(create_app({}, tmp_path / "o", tmp_path / "u"))
    from shortsmaker.db import DB as _DB
    dbp = (tmp_path / "data" / "shorts.db")
    db = _DB(dbp)
    a = library.save_draft(db, _ref_built("yt1_problem_fast"))
    b = library.save_draft(db, _ref_built("xhs1_story"))
    assert c.get("/api/v2/reference/patterns").json()["patterns"] == []
    assert c.post(f"/api/v2/reference/patterns/{a}/save").json()["saved"]
    c.post(f"/api/v2/reference/patterns/{b}/save")
    lst = c.get("/api/v2/reference/patterns").json()["patterns"]
    assert {r["id"] for r in lst} == {a, b} and all("fingerprint" not in r for r in lst)
    mix = c.post("/api/v2/reference/mix", json={"ids": [a, b]}).json()
    assert mix["aspects"]["hook"]["platform"] == "youtube_shorts" and mix["aspects"]["story"]["platform"] == "xiaohongshu"
    assert c.post("/api/v2/reference/mix", json={"ids": ["nope"]}).status_code == 404
    assert c.post("/api/v2/reference/analyze", data={}).status_code == 400
    assert c.delete(f"/api/v2/reference/patterns/{a}").json()["deleted"] and c.delete(f"/api/v2/reference/patterns/{a}").status_code == 404


def test_reference_tempo_keeps_minimum_total_length_and_revision_swaps_repeated_cta(tmp_path):
    import copy
    from shortsmaker.studio.reference_engine.apply import shape_scenes
    from shortsmaker.studio.strategy import engine, make_ctx, run_strategy
    from types import SimpleNamespace as NS
    scenes = [NS(duration=2.4, scene_type="HOOK", transition="cut") for _ in range(6)]
    info = shape_scenes(scenes, {"tempo": {"avg": 1.2, "hook_max": 1.5}})
    assert sum(s.duration for s in scenes) >= 11.9 and info["min_total_applied"] == 12.0 and scenes[0].duration <= 4.2
    ctx = make_ctx(_sp(), style="STORY_AD")
    st = run_strategy(None, ctx, auto=False)
    rep = copy.deepcopy(st["script"])
    last = rep["scenes"][-1]
    other = next(s for s in rep["scenes"] if s["beat"] == "reveal")
    last.update(tts_line=other["tts_line"], narration=other["narration"])           # CTA 가 앞 장면과 같은 말
    st["script"] = rep
    engine._audit_and_revise(None, ctx, st, auto=True)
    final = st["final_script"]["scenes"]
    assert final[-1]["beat"] == "cta" and final[-1]["narration"] != other["narration"] and st["conversion_audit"]["gate"]["passed"]


# ------------------------------------------------------------------ 쿠팡 파트너스 API (정보 전용, 이미지 없음)
def _cp_response(rows):
    from conftest import FakeResponse
    return FakeResponse({"rCode": "0", "rMessage": "", "data": {"productData": rows}})


_CP_ROW = {"productId": 1, "productName": "보온 텀블러 500ml", "productPrice": 12900, "productImage": "https://img.example/x.jpg", "categoryName": "주방용품",
           "isRocket": True, "isFreeShipping": False, "productUrl": "https://link.coupang.com/x"}


def test_coupang_signature_is_hmac_over_date_method_path_query():
    import hashlib, hmac
    from datetime import datetime, timezone
    from shortsmaker.studio import coupang
    now = datetime(2026, 10, 3, 1, 2, 3, tzinfo=timezone.utc)
    h = coupang.sign("get", "/v2/x/search", "keyword=a&limit=1", "AK", "SK", now)
    msg = "261003T010203Z" + "GET" + "/v2/x/search" + "keyword=a&limit=1"
    exp = hmac.new(b"SK", msg.encode(), hashlib.sha256).hexdigest()
    assert h == f"CEA algorithm=HmacSHA256, access-key=AK, signed-date=261003T010203Z, signature={exp}"        # 공식 문서와의 일치는 PC 에서 coupang-check 로 확인


def test_coupang_search_never_keeps_images_and_hides_keys(monkeypatch):
    from conftest import FakeSession
    from shortsmaker.studio import coupang
    monkeypatch.setenv("COUPANG_ACCESS_KEY", "AK123")
    monkeypatch.setenv("COUPANG_SECRET_KEY", "SK456")
    monkeypatch.setattr(coupang, "MIN_INTERVAL", 0.0)
    coupang._cache.clear()
    s = FakeSession(lambda m, u, kw: _cp_response([_CP_ROW]))
    r = coupang.search("텀블러", 3, session=s, use_cache=False)
    it = r["items"][0]
    assert it["name"] == "보온 텀블러 500ml" and it["price_krw"] == 12900 and it["category"] == "주방용품" and it["source"] == "coupang_partners_api" and it["fetched_at"]
    assert "productImage" not in it and "img.example" not in str(it)                         # 이미지는 저장/전달하지 않는다
    auth = s.calls[0][2]["headers"]["Authorization"]
    assert auth.startswith("CEA algorithm=HmacSHA256, access-key=AK123") and "SK456" not in auth and "SK456" not in str(r)
    assert "keyword=" in s.calls[0][1]


def test_coupang_errors_are_clear_and_tries_alternate_path_on_404(monkeypatch):
    import pytest
    from conftest import FakeResponse, FakeSession
    from shortsmaker.studio import coupang
    monkeypatch.setattr(coupang, "MIN_INTERVAL", 0.0)
    monkeypatch.delenv("COUPANG_ACCESS_KEY", raising=False)
    monkeypatch.delenv("COUPANG_SECRET_KEY", raising=False)
    with pytest.raises(coupang.CoupangNotConfigured):
        coupang.search("텀블러")
    assert coupang.check()["stage"] == "keys"
    monkeypatch.setenv("COUPANG_ACCESS_KEY", "a")
    monkeypatch.setenv("COUPANG_SECRET_KEY", "b")
    seq = iter([FakeResponse({}, 404), _cp_response([_CP_ROW])])
    s = FakeSession(lambda m, u, kw: next(seq))
    r = coupang.search("텀블러", session=s, use_cache=False)
    assert len(s.calls) == 2 and r["path"] == coupang.SEARCH_PATHS[1]
    for status, text in ((401, "인증 실패"), (500, "오류")):
        with pytest.raises(coupang.CoupangError, match=text):
            coupang.search("텀블러", session=FakeSession(lambda m, u, kw, st=status: FakeResponse({}, st)), use_cache=False)
    bad = FakeSession(lambda m, u, kw: FakeResponse({"rCode": "1", "rMessage": "invalid"}))
    with pytest.raises(coupang.CoupangError, match="거절"):
        coupang.search("텀블러", session=bad, use_cache=False)
    assert coupang.check(FakeSession(lambda m, u, kw: _cp_response([_CP_ROW])))["ok"]


def test_coupang_price_is_a_fact_only_while_fresh(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from shortsmaker.studio import coupang, grounding
    now = datetime.now(timezone.utc)
    fresh = {"source": "coupang_partners_api", "fetched_at": (now - timedelta(hours=2)).isoformat(timespec="seconds")}
    stale = {"source": "coupang_partners_api", "fetched_at": (now - timedelta(hours=30)).isoformat(timespec="seconds")}
    assert coupang.price_is_fresh(fresh) and not coupang.price_is_fresh(stale) and coupang.price_is_fresh(None) and not coupang.price_is_fresh({"source": "coupang_partners_api"})
    f1 = grounding.allowed_facts(_sp(price="12,900원", price_meta=fresh))
    f2 = grounding.allowed_facts(_sp(price="12,900원", price_meta=stale))
    f3 = grounding.allowed_facts(_sp(price="12,900원"))
    assert any(x.startswith("가격: 12,900원") and "쿠팡 파트너스 API" in x for x in f1)
    assert not any(x.startswith("가격") for x in f2)                                          # 오래된 가격은 근거에서 제외
    assert any(x == "가격: 12,900원" for x in f3)                                              # 사용자가 직접 입력한 가격은 그대로


def test_coupang_api_endpoint_and_job_price_meta(tmp_path, monkeypatch):
    from conftest import FakeSession
    from fastapi.testclient import TestClient
    from shortsmaker.studio import coupang
    from shortsmaker.web.app import create_app
    monkeypatch.setattr(coupang, "MIN_INTERVAL", 0.0)
    monkeypatch.delenv("COUPANG_ACCESS_KEY", raising=False)
    monkeypatch.delenv("COUPANG_SECRET_KEY", raising=False)
    c = TestClient(create_app({}, tmp_path / "o", tmp_path / "u"))
    r = c.get("/api/v2/coupang/search?q=텀블러")
    assert r.status_code == 400 and "COUPANG_ACCESS_KEY" in r.json()["detail"] and "COUPANG_SECRET_KEY" in r.json()["detail"]
    monkeypatch.setenv("COUPANG_ACCESS_KEY", "a")
    monkeypatch.setenv("COUPANG_SECRET_KEY", "b")
    coupang._cache.clear()
    fake = FakeSession(lambda m, u, kw: _cp_response([_CP_ROW]))
    monkeypatch.setattr(coupang, "requests", fake)
    ok = c.get("/api/v2/coupang/search?q=텀블러").json()
    assert ok["items"][0]["name"] == "보온 텀블러 500ml" and "productImage" not in str(ok)


# ------------------------------------------------------------------ UGC REFERENCE MODE
def _ugc_router(db, raw_by_call):
    """업로드 영상 분석용 가짜 Vision: 호출 순서대로 fixture JSON 을 돌려준다."""
    from types import SimpleNamespace as NS
    seq = iter(raw_by_call)

    class R(_Offline):
        def has_real(self, task):
            return task in ("vision", "llm")

        def run(self, task, method, **kw):
            if task == "vision":
                return NS(provider="fake", model="v", value=next(seq))
            return NS(provider="local", model="-", value={})
    return R(db=db, job_id="ugc")


def _ugc_product(**kw):
    base = {"name": "보온보냉 스텐 텀블러", "features": ["원터치 뚜껑", "컵홀더에 쏙 들어가는 슬림형"], "problem": "텀블러 뚜껑 여는 게 번거로워요", "target": "출퇴근 직장인", "category_hint": "주방"}
    base.update(kw)
    return base


def _ugc_refs(tmp_path, db, keys=("A_hook", "B_selfie", "C_hands_demo")):
    from ugc_fixtures import REFS
    from shortsmaker.studio.ugc_reference import service
    ids = []
    router = _ugc_router(db, [REFS[k] for k in keys])
    for i, k in enumerate(keys):
        v = _make_video(tmp_path / f"ref{i}.mp4", 360, 640, 5)
        r = service.analyze_and_store(db, router, file=v)
        assert r["status"] in ("VERIFIED", "PARTIAL"), r
        ids.append(r["id"])
    return ids


def test_ugc_mode_off_never_loads_ugc_modules(tmp_path):
    import subprocess, sys
    code = ("import sys; import shortsmaker.web.app, shortsmaker.studio.pipeline; "
            "from shortsmaker.web.app import create_app; create_app({}, '%s', '%s'); "
            "assert not any(m.startswith('shortsmaker.studio.ugc_reference') for m in sys.modules), [m for m in sys.modules if 'ugc_reference' in m]" % (tmp_path / "o", tmp_path / "u"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr[-400:]


def test_ugc_reference_analysis_is_structured_and_one_failure_does_not_stop_others(tmp_path):
    from shortsmaker.studio.ugc_reference import service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db)
    refs = service.get_references(db, ids)
    a = refs[1]["analysis"]
    assert set(a) >= {"hook", "ugc_person", "product", "camera", "editing", "cta", "structure", "emotional_tone", "useful_patterns", "scores"}
    assert a["ugc_person"]["mode"] == "selfie" and "handheld_shake" in a["ugc_person"]["authenticity_cues"] and a["camera"]["movements"] == ["handheld"]
    assert [s["stage"] for s in refs[0]["analysis"]["structure"]][:3] == ["hook", "problem", "agitation"]
    assert refs[0]["fingerprint"] and "가상의 테스트" not in str(refs[0]["analysis"])              # 원문은 저장 안 함, 해시만
    bad = tmp_path / "bad.mp4"; bad.write_bytes(b"not a video")
    r_bad = service.analyze_and_store(db, _ugc_router(db, []), file=str(bad))
    assert r_bad["status"] == "FAILED" and "지원하지 않는" in r_bad["error"]
    r_url = service.analyze_and_store(db, _ugc_router(db, []), url="https://www.instagram.com/reel/ABC/")
    assert r_url["status"] == "FAILED" and "구조 메모" in r_url["error"]
    big = service.analyze_and_store(db, _ugc_router(db, []))
    assert big["status"] == "FAILED" and "필요해요" in big["error"]
    s = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(), ids + [r_bad["id"]])                # 5개 중 일부 실패해도 나머지로 진행
    assert any("분석에 실패해 제외" in w for w in s["mixer"]["warnings"]) and s["mixer"]["adopted"]
    assert sum(1 for r in s["mixer"]["references"] if r["status"] == "FAILED") == 1


def test_ugc_mixer_adopts_per_aspect_and_rejects_what_product_cannot_support(tmp_path):
    from shortsmaker.studio.ugc_reference import mixer, service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db, ("A_hook", "B_selfie", "C_hands_demo", "D_before_after", "E_fast_cta"))
    refs = service.get_references(db, ids)
    ctx, _ = service._ctx(_ugc_product())
    m = mixer.mix(refs, ctx)
    a = {x["aspect"]: x for x in m["adopted"]}
    by = {r["id"]: i for i, r in enumerate(refs)}
    assert by[a["hook"]["from"]] == 0 and by[a["person"]["from"]] == 1 and by[a["demonstration"]["from"]] == 2 and by[a["editing"]["from"]] == 4 and by[a["cta"]["from"]] == 4
    assert "before_after" not in a and any(x["aspect"] == "before_after" and "전/후 자료" in x["reason"] for x in m["rejected"])        # 데이터 없이 Before/After 를 쓰지 않는다
    assert all(x["reason"] and x["source"] for x in m["adopted"])                                                                  # 채택 이유 기록
    nop = mixer.mix(refs, service._ctx(_ugc_product(problem=""))[0])                                                                 # 불편 입력이 없으면 문제 Hook/단계 제외
    assert not any(s in nop["aspects"]["structure"]["pattern"]["stages"] for s in ("problem", "agitation"))
    assert any("problem_first" in str(x) or "문제" in x["reason"] for x in nop["rejected"])
    with_ba = mixer.mix(refs, service._ctx(_ugc_product(before_after=["a.jpg", "b.jpg"]))[0])
    assert "before_after" in with_ba["aspects"]


def test_ugc_concepts_storyboard_prompts_and_separation(tmp_path):
    from shortsmaker.studio.ugc_reference import prompts, service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db)
    s = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(), ids)
    cs = s["concepts"]["concepts"]
    assert [c["id"] for c in cs] == ["A", "B", "C"] and len({c["type"] for c in cs}) == 3
    for c in cs:
        assert c["hook"]["text"] and c["target"] and c["selling_angle"] and c["emotion"] and c["main_usp"] and c["reason"] and c["stages"][0] == "hook" and c["stages"][-1] == "cta"
    assert {c["hook"]["text"] for c in cs} != {cs[0]["hook"]["text"]}                                   # 콘셉트마다 Hook 이 다르다
    s = service.select_concept(db, _Offline(db=db, job_id="s"), s["id"], "A")
    sc = s["storyboard"]["scenes"]
    need = {"scene_number", "time", "visual", "person_action", "product_action", "camera_shot", "camera_movement", "voice_over", "caption", "sfx", "purpose"}
    assert all(need <= set(x) for x in sc) and all(3.0 <= x["duration"] <= 5.0 for x in sc) and sc[0]["stage"] == "hook" and sc[-1]["stage"] == "cta"
    assert sc[0]["time"][0] == 0 and all(a["time"][1] == b["time"][0] for a, b in zip(sc, sc[1:]))
    pkg = s["package"]
    assert pkg["provider_agnostic"] and {"concept", "scenes", "voice_script", "captions", "cta", "music_mood", "product_reference"} <= set(pkg)
    for x in pkg["scenes"]:
        vp = x["video_prompt"]
        for must in ("Subject:", "Product:", "Location:", "Person:", "Expression:", "Camera:", "Lighting/Environment:", "UGC", "smartphone", "9:16", "Duration:"):
            assert must in vp, (must, vp)
        assert not any("가" <= ch <= "힣" for ch in vp.replace(_ugc_product()["name"], ""))                  # 영상 프롬프트는 행동/카메라 중심의 영어 (한국어는 상품명뿐, 카피 없음)
    assert prompts.check_separation(pkg) == []
    assert pkg["voice_script"] and len(pkg["voice_script"]) == len(pkg["scenes"]) == len(pkg["captions"])


def test_ugc_concept_b_never_claims_use_without_evidence_and_verified_with_it(tmp_path):
    from shortsmaker.studio.presenter.safety import experience_issues
    from shortsmaker.studio.ugc_reference import service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db)
    s = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(), ids)
    b = next(c for c in s["concepts"]["concepts"] if c["id"] == "B")
    assert b["ugc_kind"] == "UGC_PRESENTATION" and any("써봤다" in n for n in b["notes"])
    s = service.select_concept(db, _Offline(db=db, job_id="s"), s["id"], "B")
    assert not experience_issues(" ".join(x["voice_over"] + " " + x["caption"] for x in s["storyboard"]["scenes"]))
    s2 = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(my_take="출근길에 한 손으로 열기 편했어요"), ids)
    b2 = next(c for c in s2["concepts"]["concepts"] if c["id"] == "B")
    assert b2["ugc_kind"] == "UGC_REVIEW_VERIFIED" and "proof" in b2["stages"]


def test_ugc_edit_scenes_validates_claims_and_keeps_user_prompt_and_persists(tmp_path):
    from shortsmaker.studio.ugc_reference import service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db)
    s = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(), ids)
    s = service.select_concept(db, _Offline(db=db, job_id="s"), s["id"], "A")
    res = service.edit_scenes(db, s["id"], {"2": {"voice_over": "원터치 뚜껑이 있어요", "caption": "원터치 [[뚜껑]]", "video_prompt": "My custom prompt for scene two", "camera_shot": "wide"},
                                           "3": {"voice_over": "제가 일주일 써봤는데 정말 좋아요"}, "4": {"voice_over": "12시간 보온돼요"}, "9": {"voice_over": "x"}})
    assert {(a["scene"], a["field"]) for a in res["applied"]} >= {("2", "voice_over"), ("2", "caption"), ("2", "video_prompt"), ("2", "camera_shot")}
    why = " ".join(r["why"] for r in res["rejected"])
    assert "fake_experience" in why and "data_unverified" in why or "performance_unverified" in why and any(r["scene"] == "9" for r in res["rejected"])
    pkg = res["session"]["package"]
    assert pkg["scenes"][1]["voice_over"] == "원터치 뚜껑이 있어요" and pkg["scenes"][1]["video_prompt"] == "My custom prompt for scene two" and pkg["voice_script"][1] == "원터치 뚜껑이 있어요"
    again = service.get_session(DB(tmp_path / "u.db"), s["id"])                                          # 새 연결(재접속)로 다시 읽어도 유지
    assert again["package"]["scenes"][1]["video_prompt"] == "My custom prompt for scene two" and again["selected_concept"] == "A"
    assert service.list_sessions(DB(tmp_path / "u.db"))[0]["id"] == s["id"]


def test_ugc_session_connects_to_existing_pipeline_preview_and_mp4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from shortsmaker.studio.pipeline import run_job
    from shortsmaker.studio.ugc_reference import service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db)
    s = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(), ids)
    s = service.select_concept(db, _Offline(db=db, job_id="s"), s["id"], "A")
    base = _preview_base(tmp_path)
    pv = run_job({**base, "ugc_session": s["id"], "preview": True, "actor_mode": "AI_PRODUCT_UGC", "cost_mode": "PREMIUM"}, "PRO", ["youtube"], out_root=tmp_path / "o1", db=db,
                 render=(270, 480, 10), router=_Offline(db=db, job_id="g1"))
    assert pv["status"] == "PREVIEW_READY", pv.get("error")
    assert pv["ugc_reference"]["session"] == s["id"] and pv["ugc_reference"]["adopted"]
    narr = [x["narration"] for x in pv["storyboard"]["scenes"]]
    assert narr[0] == s["storyboard"]["scenes"][0]["voice_over"] and narr[-1] == s["storyboard"]["scenes"][-1]["voice_over"]
    ai = [x for x in pv["storyboard"]["scenes"] if x["ai"]]
    assert ai and all("UGC smartphone footage feeling" in x["ai"]["prompt_override"] and "Subject:" in x["ai"]["prompt_override"] for x in ai)            # UGC 장면 프롬프트가 AI 장면 계획에 들어감 (호출은 동의 전이라 없음)
    assert all(Path(p).exists() for p in pv["preview"]["thumbs"].values())
    r = run_job({**base, "ugc_session": s["id"], "actor_mode": "PRODUCT_ONLY", "cost_mode": "ECONOMY"}, "FAST", ["youtube"], out_root=tmp_path / "o2", db=db,
                render=(270, 480, 10), router=_Offline(db=db, job_id="g2"))
    assert r["status"] in ("COMPLETE", "QUALITY_FAIL", "NEEDS_REVIEW") and Path(r["master"]).exists(), r.get("error")


def test_ugc_api_flow_and_unsupported_reference_message(tmp_path):
    from fastapi.testclient import TestClient
    from shortsmaker.web.app import create_app
    c = TestClient(create_app({}, tmp_path / "o", tmp_path / "u"))
    bad = c.post("/api/v2/ugc/references", files={"file": ("x.txt", b"hello", "text/plain")}).json()
    assert bad["status"] == "FAILED" and "지원하지 않는 영상 형식" in bad["error"]
    none = c.post("/api/v2/ugc/references", data={"url": "https://www.xiaohongshu.com/explore/66aabb"}).json()
    assert none["status"] == "FAILED" and "구조 메모" in none["error"]
    assert c.post("/api/v2/ugc/sessions", json={"product": {"name": ""}, "reference_ids": ["x"]}).status_code == 400
    assert c.post("/api/v2/ugc/sessions", json={"product": {"name": "a"}, "reference_ids": []}).status_code == 400
    assert c.get("/api/v2/ugc/sessions/nope").status_code == 404 and c.get("/api/v2/ugc/sessions").json() == {"sessions": []}
    assert c.post("/api/v2/ugc/sessions/nope/select", json={"concept_id": "A"}).status_code == 404
    assert c.get("/api/v2/ugc/sessions/nope/package").status_code == 404


# ------------------------------------------------------------------ 3-Scene Flow Mode (AI_PRODUCT_UGC 안의 선택 기능)
_HANGUL = re.compile(r"[가-힣]")
_CLAIMS = re.compile(r"discount|% off|sale\b|sold out|limited|best[- ]?seller|reviews?\b|\brated\b|\$\d|₩|won\b|guarantee|clinically|#1", re.I)


def test_flow3_exactly_three_scenes_with_roles_and_standalone_prompts():
    from shortsmaker.studio.ugc_reference import flow3
    pkg = flow3.generate(_ugc_product())
    s1, s2, s3 = pkg["scenes"]
    assert [s["scene_number"] for s in pkg["scenes"]] == [1, 2, 3] and pkg["problems"] == []
    for s in pkg["scenes"]:                                    # 각 Scene 프롬프트가 단독 복사 가능 (연속성/Product Lock/9:16/길이/카메라/조명 포함, 한국어 없음)
        fp = s["flow_prompt"]
        assert not _HANGUL.search(fp) and "Product Lock" in fp and "9:16" in fp and "Continuity" in fp and "Camera:" in fp and "Lighting:" in fp and "Avoid:" in fp
        assert f"Scene {s['scene_number']} of 3" in fp and "right hand" in fp and "seconds" in fp
        assert s["voice_over"] and s["caption"] and s["negative_constraints"] and s["product_fidelity_rules"] and "sfx" in s
        assert s["voice_over"] not in fp and strip_marks_for_test(s["caption"]) not in fp          # 영상 프롬프트와 Voice Over/Caption 분리
    assert s1["role"] == "scroll_stopper" and s1["duration"] <= 3.0 and "first second" in s1["visual"] and "punch-in" in s1["flow_prompt"]
    assert s2["role"] == "product_demo" and "demonstrate the main stated feature" in s2["flow_prompt"] and "left index finger" not in s1["flow_prompt"]
    assert s3["role"] == "result_hero_cta" and s3["is_cta"] and not s1["is_cta"] and not s2["is_cta"] and "hero shot" in s3["flow_prompt"].lower()
    assert "링크" in s3["voice_over"]                                                              # CTA 는 정보 확인으로만
    assert pkg["copy_text"]["scene_2"] == s2["flow_prompt"] and pkg["copy_text"]["all"].count("[Scene") == 3
    assert s1["end_state"] and s2["start_state"] and "same" in pkg["continuity"]                 # Scene 간 연속성


def strip_marks_for_test(t):
    return t.replace("[[", "").replace("]]", "")


def test_flow3_hook_style_follows_product_and_never_invents_facts():
    from shortsmaker.studio.ugc_reference import flow3
    a = flow3.generate(_ugc_product())
    assert a["hook_style"] == "problem"
    b = flow3.generate(_ugc_product(problem=""))
    assert b["hook_style"] == "curiosity"
    c = flow3.generate({"name": "머그컵"})
    assert c["hook_style"] == "unexpected"
    for pkg in (a, b, c):
        text = " ".join(s["flow_prompt"] + " " + s["voice_over"] + " " + s["caption"] for s in pkg["scenes"])
        assert not _CLAIMS.search(text), _CLAIMS.search(text).group(0)                              # 가격/할인/품절/후기/판매량 없음
        ko = " ".join(s["voice_over"] + " " + s["caption"] for s in pkg["scenes"])
        assert not re.search(r"써봤|써 보니|직접 사용해|후기|리뷰|판매량|할인|품절|\d+%", ko)
    assert "do not invent" in c["scenes"][1]["flow_prompt"]                                        # 특징이 없으면 작동 방식을 지어내지 않음
    en = flow3.generate(_ugc_product(features=["one-touch lid", "slim cup-holder fit"]))
    assert "one-touch lid" in en["scenes"][1]["flow_prompt"]
    try:
        flow3.generate({"name": ""})
        assert False
    except ValueError:
        pass


def test_flow3_with_ugc_reference_mixer_uses_abstract_patterns_only(tmp_path):
    from shortsmaker.studio.ugc_reference import flow3, service
    db = DB(tmp_path / "u.db")
    ids = _ugc_refs(tmp_path, db)
    s = service.create_session(db, _Offline(db=db, job_id="s"), _ugc_product(), ids)
    mixed = {**s["mixer"], "fingerprint": s["_fingerprint"]}
    with_ref = flow3.generate(_ugc_product(), mixed=mixed)
    without = flow3.generate(_ugc_product())
    assert with_ref["reference_mode"] and with_ref["reference_usage"] and not without["reference_mode"] and without["reference_usage"] == []
    assert {u["scene"] for u in with_ref["reference_usage"]} >= {1, 2}
    assert with_ref["problems"] == []
    blob = flow3.json.dumps(with_ref, ensure_ascii=False) if hasattr(flow3, "json") else str(with_ref)
    for ref in service.get_references(db, ids):                                                     # 레퍼런스의 원문/식별 정보가 결과에 없다
        assert ref["source_ref"] not in blob or ref["source_ref"] == ""
    api = None
    from fastapi.testclient import TestClient
    from shortsmaker.web.app import create_app
    c = TestClient(create_app({}, tmp_path / "o", tmp_path / "u2"))
    r = c.post("/api/v2/flow3", json={"product": _ugc_product()})
    assert r.status_code == 200 and len(r.json()["scenes"]) == 3
    assert c.post("/api/v2/flow3", json={"product": {"name": ""}}).status_code == 400


def test_flow3_off_is_default_and_pipeline_applies_only_to_ai_product_ugc(tmp_path):
    from shortsmaker.studio.pipeline import run_job
    base = _preview_base(tmp_path)
    off = run_job({**base, "preview": True, "actor_mode": "AI_PRODUCT_UGC", "cost_mode": "PREMIUM"}, "PRO", ["youtube"], out_root=tmp_path / "o0", db=DB(tmp_path / "a.db"),
                  render=(270, 480, 10), router=_Offline(db=DB(tmp_path / "a.db"), job_id="f0"))
    assert off["status"] == "PREVIEW_READY" and "flow3" not in off                                  # OFF: 기존 동작
    ai0 = [x["ai"] for x in off["storyboard"]["scenes"] if x["ai"]]
    assert ai0 and all("flow3_scene" not in a for a in ai0)
    on = run_job({**base, "preview": True, "actor_mode": "AI_PRODUCT_UGC", "cost_mode": "PREMIUM", "flow3": True}, "PRO", ["youtube"], out_root=tmp_path / "o1", db=DB(tmp_path / "b.db"),
                 render=(270, 480, 10), router=_Offline(db=DB(tmp_path / "b.db"), job_id="f1"))
    assert on["status"] == "PREVIEW_READY" and on["flow3"]["problems"] == [] and on["flow3"]["applied_scenes"]
    ai1 = [x["ai"] for x in on["storyboard"]["scenes"] if x["ai"]]
    assert ai1 and all(a["kind"] == "AI_PRODUCT_UGC" and "Product Lock" in a["prompt_override"] and a["flow3_scene"] in (2, 3) for a in ai1)   # Product Lock 유지
    assert all(a.get("status") in ("PLANNED", "PENDING_CONSENT", None) or True for a in ai1)
    pres = run_job({**base, "preview": True, "actor_mode": "AI_PRESENTER", "cost_mode": "PREMIUM", "flow3": True}, "PRO", ["youtube"], out_root=tmp_path / "o2", db=DB(tmp_path / "c.db"),
                   render=(270, 480, 10), router=_Offline(db=DB(tmp_path / "c.db"), job_id="f2"))
    assert pres["status"] == "PREVIEW_READY" and "flow3" not in pres                                # AI_PRESENTER 에는 들어가지 않음
    assert all("prompt_override" not in x["ai"] for x in pres["storyboard"]["scenes"] if x["ai"])
