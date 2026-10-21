"""Offline checks: MOSS is opt-in, background-only, and keeps actual product untouched."""
import io
import json

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from shortsmaker.studio.moss_image import (
    _check_https_url, _request, compose_cover, generate_background,
    make_plan, plan_from_job, validate_size,
)
from shortsmaker.web.app import create_app


def test_plan_defaults_9_16_and_background_only():
    plan = make_plan("empty natural desk", product_name="접이식 거치대", headline="정리 끝")
    assert plan["model"] == "moss-image-sft-1.0"
    assert plan["size"] == "720x1280"
    assert plan["type"] == "BACKGROUND_ONLY"
    assert plan["identity_preserved"] == "COMPOSITE_ORIGINAL_PHOTO"
    payload = _request(plan)
    assert payload["n"] == 1 and payload["response_format"] == "url"
    assert "NO product" in payload["prompt"]
    assert "접이식 거치대" not in payload["prompt"]  # do not hallucinate a replacement product


@pytest.mark.parametrize("size", ["", "720x999", "1600x1600", "1280x1920", "256x", "100x100"])
def test_rejects_unsupported_sizes(size):
    with pytest.raises(ValueError):
        validate_size(size)


def test_requires_explicit_approval_and_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MOSS_API_KEY", raising=False)
    plan = make_plan()
    class NoNetwork:
        def post(self, *args, **kwargs):
            raise AssertionError("network must not be called")
    with pytest.raises(PermissionError):
        generate_background(plan, tmp_path / "out.png", http=NoNetwork())
    with pytest.raises(ValueError, match="MOSS_API_KEY"):
        generate_background(plan, tmp_path / "out.png", approve_paid=True, http=NoNetwork())


def test_paid_request_is_one_image_and_original_photo_is_preserved(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (720, 1280), "#7b89a3").save(buf, format="PNG")
    bg_bytes = buf.getvalue()

    class FakePost:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": [{"url": "https://cdn.example.org/generated.png"}],
                    "usage": {"generated_images": 1}}
    class FakeGet:
        status_code = 200
        headers = {"Content-Type": "image/png"}
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield bg_bytes
    class FakeHttp:
        def __init__(self):
            self.calls = []
        def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            return FakePost()
        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            return FakeGet()
    http = FakeHttp()
    plan = make_plan(headline="이건 뭐지?")
    report = generate_background(plan, tmp_path / "background.png",
                                 approve_paid=True, api_key="test-placeholder-key", http=http)
    assert report["usage"]["generated_images"] == 1
    assert len(http.calls) == 2
    assert http.calls[0][2]["json"]["n"] == 1
    assert http.calls[0][2]["headers"]["Authorization"] == "Bearer test-placeholder-key"
    image = tmp_path / "product.jpg"
    Image.new("RGB", (200, 300), "orange").save(image)
    before = image.read_bytes()
    cover = compose_cover(tmp_path / "background.png", image, "이건 뭐지?", tmp_path / "cover.png")
    assert cover.is_file() and image.read_bytes() == before
    with Image.open(cover) as im:
        assert im.size == (720, 1280)


@pytest.mark.parametrize("url", [
    "http://cdn.example.org/x.png",
    "https://localhost/a.png",
    "https://127.0.0.1/a.png",
    "https://10.2.3.4/a.png",
    "file:///etc/passwd",
    "https://name:secret@site.com/image.png",
])
def test_blocks_unsafe_download_urls(url):
    with pytest.raises(ValueError):
        _check_https_url(url)


def test_from_existing_shop_shorts_job(tmp_path):
    photo = tmp_path / "real_product.png"
    Image.new("RGB", (80, 80), "white").save(photo)
    job = tmp_path / "result.json"
    job.write_text(json.dumps({
        "status": "QUALITY_FAIL",
        "identity": {"name": "스마트 거치대", "photos": [{"path": str(photo)}]},
    }), encoding="utf-8")
    plan, source = plan_from_job(job, style="tech")
    assert source == photo and plan["headline"] == "스마트 거치대"
    data = json.loads(job.read_text())
    data["status"] = "FAILED"
    job.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        plan_from_job(job)


def test_web_plan_and_paid_consent_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("MOSS_API_KEY", raising=False)
    client = TestClient(create_app({}, tmp_path / "out", tmp_path / "uploads"))
    assert client.get("/moss").status_code == 200
    plan = client.post("/api/moss/plan", json={"headline": "테스트 제목"})
    assert plan.status_code == 200 and plan.json()["paid_call_required"]
    assert client.post("/api/moss/generate", data={}).status_code == 403
    assert client.post("/api/moss/generate", data={"approve_paid": "true"}).status_code == 503
    locked = TestClient(create_app({}, tmp_path / "locked_out", tmp_path / "locked_uploads", access_code="test_code"),
                        follow_redirects=False)
    assert locked.get("/moss").status_code == 303
    assert locked.post("/api/moss/generate", data={"approve_paid": "true"}).status_code == 401
