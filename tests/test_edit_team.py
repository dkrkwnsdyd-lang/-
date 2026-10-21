"""영상 편집팀 V0.3 API 회귀 테스트. 유료 모델 호출이나 실제 SNS 게시는 하지 않는다."""
from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from shortsmaker.web.app import create_app
from shortsmaker.web import edit_team


def photo() -> bytes:
    out = BytesIO()
    Image.new("RGB", (80, 120), "#345678").save(out, "PNG")
    return out.getvalue()


def test_edit_team_page_and_health(tmp_path):
    with TestClient(create_app(output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads")) as client:
        page = client.get("/edit-team")
        assert page.status_code == 200
        assert "영상 편집팀 발동" in page.text
        assert client.get("/api/edit-team/health").json()["version"] == "0.3"


def test_edit_team_rejects_malformed_image(tmp_path):
    with TestClient(create_app(output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads")) as client:
        res = client.post("/api/edit-team/jobs", files={
            "photo1": ("bad.jpg", b"not an image", "image/jpeg"),
            "photo2": ("good.png", photo(), "image/png"),
        }, data={"product_name": "테스트", "disclosure": "광고"})
        assert res.status_code == 415


def test_edit_team_job_success_without_render_cost(tmp_path, monkeypatch):
    def fake_render(folder):
        (folder / "result.mp4").write_bytes(b"fake-mp4")
        edit_team._set_state(folder, status="completed", stage="완료", progress=100,
                             download_url=f"/api/edit-team/jobs/{folder.name}/file")

    class Immediate:
        def submit(self, fn, *args):
            fn(*args)

    monkeypatch.setattr(edit_team, "_POOL", Immediate())
    monkeypatch.setattr(edit_team, "_render", fake_render)
    with TestClient(create_app(output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads")) as client:
        res = client.post("/api/edit-team/jobs", files={
            "photo1": ("one.png", photo(), "image/png"),
            "photo2": ("two.png", photo(), "image/png"),
        }, data={"product_name": "휴대용 거치대", "disclosure": "제휴 활동 수수료 발생 가능"})
        assert res.status_code == 202, res.text
        job = res.json()
        assert job["status"] in ("queued", "completed")
        detail = client.get(f"/api/edit-team/jobs/{job['id']}")
        assert detail.json()["status"] == "completed"
        dl = client.get(detail.json()["download_url"])
        assert dl.status_code == 200
        assert dl.content == b"fake-mp4"
        assert client.get("/api/edit-team/jobs/../../bad/file").status_code in (404, 405)


def test_disclosure_required(tmp_path):
    with TestClient(create_app(output_dir=tmp_path / "output", upload_dir=tmp_path / "uploads")) as client:
        res = client.post("/api/edit-team/jobs", files={
            "photo1": ("one.png", photo(), "image/png"),
            "photo2": ("two.png", photo(), "image/png"),
        }, data={"product_name": "제품", "disclosure": " "})
        assert res.status_code == 422
