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


def test_v2_job_boxes_validation(photos, tmp_path):
    client = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    files = [("photos", (photos[0].name, photos[0].read_bytes(), "image/jpeg"))]
    bad = client.post("/api/v2/jobs", files=files, data={"boxes": "not json"})
    assert bad.status_code == 400


def test_v2_job_feature_photos_validation(photos, tmp_path):
    client = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    files = [("photos", (p.name, p.read_bytes(), "image/jpeg")) for p in photos[:2]]
    assert client.post("/api/v2/jobs", files=files, data={"feature_photos": "[1,2"}).status_code == 400
    assert client.post("/api/v2/jobs", files=files, data={"feature_photos": "[1]"}).status_code == 400


# ------------------------------------------------------------------ 접근 암호 / PWA
def _locked(tmp_path, code="s3cret"):
    return TestClient(create_app({}, tmp_path / "out", tmp_path / "up", access_code=code), follow_redirects=False)


def test_locked_app_blocks_everything_except_public_paths(tmp_path):
    c = _locked(tmp_path)
    assert c.get("/").status_code == 303 and c.get("/").headers["location"] == "/login"
    assert c.get("/api/v2/jobs").status_code == 401
    assert c.get("/api/v2/control-center").status_code == 401
    assert c.get("/outputs/x.mp4").status_code == 401
    assert c.post("/api/v2/jobs", data={"mode": "PRO"}).status_code == 401
    for path in ("/login", "/manifest.webmanifest", "/sw.js", "/healthz", "/favicon.ico", "/icons/icon-192.png"):
        assert c.get(path).status_code == 200, path
    assert "Service-Worker-Allowed" in c.get("/sw.js").headers


def test_login_cookie_and_bearer(tmp_path):
    c = _locked(tmp_path)
    assert c.post("/login", data={"code": "wrong"}).status_code == 401
    ok = c.post("/login", data={"code": "s3cret"})
    assert ok.status_code == 200 and "ss_auth" in ok.headers["set-cookie"] and "HttpOnly" in ok.headers["set-cookie"]
    assert c.get("/api/v2/jobs").status_code == 200                 # 쿠키로 통과
    assert _locked(tmp_path).get("/api/v2/jobs", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert _locked(tmp_path).get("/api/v2/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/logout").status_code == 200


def test_login_is_rate_limited(tmp_path):
    c = _locked(tmp_path)
    codes = [c.post("/login", data={"code": f"bad{i}"}).status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    assert c.post("/login", data={"code": "s3cret"}).status_code == 429      # 잠금 중에는 맞는 암호도 거절


def test_access_code_resolution():
    from shortsmaker.web.auth import resolve_access_code
    assert resolve_access_code("127.0.0.1", None) == (None, False)          # 로컬 전용은 암호 없이
    code, generated = resolve_access_code("0.0.0.0", None)                   # 외부에 열면 자동 생성
    assert generated and len(code) >= 6
    assert resolve_access_code("0.0.0.0", "mine") == ("mine", False)


def test_local_app_has_no_login(tmp_path):
    c = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"), follow_redirects=False)
    assert c.get("/").status_code == 200 and c.get("/api/v2/jobs").status_code == 200
    m = c.get("/manifest.webmanifest").json()
    assert m["display"] == "standalone" and {i["sizes"] for i in m["icons"]} >= {"192x192", "512x512"}


def test_upload_limits(photos, tmp_path):
    c = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    many = [("photos", (f"{i}.jpg", photos[0].read_bytes(), "image/jpeg")) for i in range(13)]
    assert c.post("/api/v2/jobs", files=many, data={}).status_code == 400
