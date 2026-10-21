"""No-network tests for the optional Hypit handoff."""
import json
from pathlib import Path

import pytest

from shortsmaker.hypit_bridge import prepare_hypit


@pytest.fixture
def job(tmp_path):
    image = tmp_path / "my_product.jpg"
    image.write_bytes(b"fake image for copy test")
    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "job_id": "abc123",
        "status": "QUALITY_FAIL",
        "identity": {
            "name": "접이식 거치대",
            "distinctive_features": ["각도 조절"],
            "color_reference": ["black"],
            "photos": [{"path": str(image)}],
        },
        "plan": {
            "story_pattern": "problem_solution",
            "scenes": [
                {"scene_id": "S1", "beat": "hook", "duration": 3,
                 "caption": "어디에 두지?", "reference_image": str(image),
                 "unknown_private_field": "never export"}
            ],
        },
        "reference": {"source": "https://example.com/video", "status": "UNVERIFIED"},
        "qa": {"verdict": "QUALITY_FAIL", "scores": {"overall": 64}},
        "compliance": {"platforms": {"youtube": {"verdict": "BLOCK"}}},
        "router_trace": {"secret": "must not leak"},
    }, ensure_ascii=False), encoding="utf-8")
    return result


def test_prepare_generates_manifest_brief_and_local_asset(job):
    brief = prepare_hypit(job)
    assert brief.is_file()
    text = brief.read_text(encoding="utf-8")
    assert "Hypit" in text
    assert "유료 API 호출 전에" in text
    data = json.loads((brief.parent / "shop_shorts_manifest.json").read_text(encoding="utf-8"))
    assert data["product"]["name"] == "접이식 거치대"
    assert data["video"]["duration_seconds"] == 3
    assert data["original_status"] == "QUALITY_FAIL"
    assert data["quality"]["must_retest"] is True
    assert data["compliance"]["must_retest"] is True
    assert data["compliance"]["existing_platform_verdicts"]["youtube"] == "BLOCK"
    assert data["reference"]["structure_only"] is True
    assert data["assets"] == ["assets/product_01.jpg"]
    assert data["video"]["scenes"][0]["reference_image"] == "assets/product_01.jpg"
    serialized = json.dumps(data, ensure_ascii=False)
    assert "never export" not in serialized
    assert "must not leak" not in serialized
    assert (brief.parent / "assets/product_01.jpg").is_file()


def test_disabled_copy_references_existing_file(job):
    brief = prepare_hypit(job, job.parent / "agent_handoff", copy_images=False)
    data = json.loads((brief.parent / "shop_shorts_manifest.json").read_text(encoding="utf-8"))
    assert data["assets"] == [str(job.parent / "my_product.jpg")]
    assert not (brief.parent / "assets").exists()


@pytest.mark.parametrize("status", ["FAILED", "STRATEGY_BLOCKED"])
def test_blocked_jobs_are_rejected(job, status):
    data = json.loads(job.read_text(encoding="utf-8"))
    data["status"] = status
    job.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_hypit(job)


def test_missing_scenes_rejected(job):
    data = json.loads(job.read_text(encoding="utf-8"))
    data["plan"]["scenes"] = []
    job.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="plan.scenes"):
        prepare_hypit(job)


def test_missing_source_image_reported_not_downloaded(job):
    data = json.loads(job.read_text(encoding="utf-8"))
    data["identity"]["photos"][0]["path"] = "https://example.org/private.jpg"
    data["plan"]["scenes"][0]["reference_image"] = "https://example.org/private.jpg"
    job.write_text(json.dumps(data), encoding="utf-8")
    brief = prepare_hypit(job)
    m = json.loads((brief.parent / "shop_shorts_manifest.json").read_text(encoding="utf-8"))
    assert m["assets"] == []
    assert m["missing_images"] == ["https://example.org/private.jpg"]
    assert m["video"]["scenes"][0]["reference_image"] is None
