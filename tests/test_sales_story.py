"""Regression tests for preproduction ads; never call AI providers or render."""
import pytest
from fastapi.testclient import TestClient

from shortsmaker.studio.sales_story import build_sales_story
from shortsmaker.web.app import create_app


@pytest.fixture
def product():
    return {
        "name": "차량용 휴대폰 거치대",
        "problem": "휴대폰이 흔들려 화면을 보기 불편함",
        "target": "차량 이용자",
        "features": ["각도 조절 기능"],
        "photos": ["product1.jpg", "product2.jpg"],
        "review_quotes": ["별점 5점 최고예요!"],
    }


def test_three_real_distinct_directions_and_exact_20s(product):
    result = build_sales_story(product)
    vs = result["variants"]
    assert [v["id"] for v in vs] == ["PAIN_FIRST", "BEFORE_AFTER", "FEATURE_FIRST"]
    assert len({v["label"] for v in vs}) == 3
    assert all(v["duration_seconds"] == 20 and len(v["scenes"]) == 5 for v in vs)
    assert all([s["start"] for s in v["scenes"]] == [0, 3, 7, 12, 16] for v in vs)
    assert all([s["end"] for s in v["scenes"]] == [3, 7, 12, 16, 20] for v in vs)
    assert vs[0]["scenes"][0]["comparison_role"] == "before"
    assert vs[1]["scenes"][3]["comparison_role"] == "after_needs_proof"
    assert vs[1]["missing_inputs"] == ["before_after_media"]
    assert vs[0]["ready_for_creative_preview"] is True


def test_unverified_reviews_and_results_never_appear_in_public_ad_copy(product):
    result = build_sales_story(product)
    spoken = " ".join(s["narration"] + " " + s["caption"]
                      for v in result["variants"] for s in v["scenes"])
    assert "별점 5점" not in spoken
    assert "최고예요" not in spoken
    assert "효과 보장" not in spoken
    assert result["review_leads_count"] == 1
    assert all(not e["verified"] for e in result["evidence"])
    assert result["publication_status"] == "NEEDS_REVIEW"
    assert all(not v["ready_for_publish"] for v in result["variants"])
    assert result["cost"]["paid_calls_made"] is False
    assert result["render_status"] == "storyboard_only"


def test_before_after_media_allows_preview_but_not_unverified_performance(product):
    product["before_after"] = ["real_before.jpg", "real_after.jpg"]
    result = build_sales_story(product)
    variant = result["variants"][1]
    assert variant["missing_inputs"] == []
    assert variant["ready_for_creative_preview"]
    assert not variant["ready_for_publish"]


def test_missing_details_flagged_instead_of_hallucinated():
    result = build_sales_story({"name": "투명 케이스"})
    assert all(not v["ready_for_creative_preview"] for v in result["variants"])
    assert "고객이 느끼는 실제 불편함" in result["missing_research"]
    assert "실제 확인한 제품 특징" in result["missing_research"]
    assert "실제 제품 사진" in result["missing_research"]


def test_invalid_empty_input_is_rejected():
    with pytest.raises(ValueError):
        build_sales_story({})
    with pytest.raises(ValueError):
        build_sales_story([])


def test_api_returns_three_concepts_and_rejects_empty(tmp_path, product):
    app = create_app({}, tmp_path / "out", tmp_path / "up")
    client = TestClient(app)
    okay = client.post("/api/v2/ads/plan", json={"product": product})
    assert okay.status_code == 200, okay.text
    assert len(okay.json()["variants"]) == 3
    no_data = client.post("/api/v2/ads/plan", json={"product": {}})
    assert no_data.status_code == 400
