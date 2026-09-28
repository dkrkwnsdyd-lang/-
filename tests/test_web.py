from fastapi.testclient import TestClient

from shortsmaker.web.app import create_app


def test_render_and_publish_validation(photos, tmp_path):
    cfg = {"video": {"width": 216, "height": 384, "fps": 10, "seconds_per_image": 0.5,
                     "transition": 0, "preset": "ultrafast"}}
    client = TestClient(create_app(cfg, tmp_path / "out", tmp_path / "up"))

    assert client.get("/").status_code == 200
    plats = client.get("/api/platforms").json()
    assert {p["id"] for p in plats} == {"youtube", "instagram", "threads", "tiktok"}

    files = [("files", (p.name, p.read_bytes(), "image/jpeg")) for p in photos]
    r = client.post("/api/render", files=files, data={"title": "t", "captions": "a\nb",
                                                        "seconds": "0.5", "transition": "0"})
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert client.get(f"/outputs/{name}").status_code == 200

    r = client.post("/api/publish", json={"name": "../x.mp4", "title": "t", "platforms": ["tiktok"]})
    assert r.status_code == 404
    r = client.post("/api/publish", json={"name": name, "title": "t", "platforms": ["tiktok"]})
    assert r.status_code == 200 and r.json()[0]["ok"] is False


def test_render_requires_input(tmp_path):
    client = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    assert client.post("/api/render", data={"title": "x"}).status_code == 400


def test_v2_pages_and_control_center(tmp_path):
    client = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    assert "SHOP SHORTS" in client.get("/").text
    assert client.get("/classic").status_code == 200
    assert client.get("/control").status_code == 200
    rows = client.get("/api/v2/control-center").json()
    assert {r["provider"] for r in rows} >= {"openai", "google", "groq", "elevenlabs", "pexels", "pixabay"}
    fb = client.post("/api/v2/control-center/test-fallback").json()
    assert fb["ok"] and fb["trace"][0]["ok"] is False
    assert client.post("/api/v2/jobs", data={"mode": "PRO"}).status_code == 400
    assert client.get("/api/v2/jobs/nope").status_code == 404
