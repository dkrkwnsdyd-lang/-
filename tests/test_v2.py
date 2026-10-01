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
