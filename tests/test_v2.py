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
    assert any(s["shot"] == "video_clip" for s in r["edl"]["shots"])
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
