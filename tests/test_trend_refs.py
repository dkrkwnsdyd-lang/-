from fastapi.testclient import TestClient

from shortsmaker.web.app import create_app


def item(i="64f1a2b3c4d5e6f7a8b9c0d1", **kw):
    base = {"id": i, "platform": "xiaohongshu", "url": f"https://www.xiaohongshu.com/explore/{i}", "title": "29💰可折叠沙发",
            "author": "家居君", "likes": 5400, "collects": None, "comments": None, "mult": 65.06, "score": 80, "tier": "폭발",
            "context": "与电影夜奔", "savedAt": "2026-10-17T05:00:00.000Z"}
    return {**base, **kw}


def test_trend_refs_add_update_list_delete(tmp_path):
    c = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    assert c.get("/trends").status_code == 200
    assert "트렌드 레퍼런스" in c.get("/").text

    r = c.post("/api/v2/trend-refs", json={"items": [item(), item("abc123", mult=2.0, likes=166, tier="보통")]})
    assert r.status_code == 200 and r.json() == {"added": 2, "updated": 0, "skipped": 0, "total": 2}

    # 같은 게시물을 다시 보내면 숫자만 갱신
    r = c.post("/api/v2/trend-refs", json={"items": [item(likes=6000, mult=70.0)]})
    assert r.json() == {"added": 0, "updated": 1, "skipped": 0, "total": 2}

    rows = c.get("/api/v2/trend-refs").json()
    assert [x["source_id"] for x in rows] == ["64f1a2b3c4d5e6f7a8b9c0d1", "abc123"]  # 성과배수 높은 순
    assert rows[0]["likes"] == 6000 and rows[0]["id"] == "xiaohongshu:64f1a2b3c4d5e6f7a8b9c0d1"
    assert c.get("/api/v2/trend-refs?platform=youtube").json() == []

    assert c.delete("/api/v2/trend-refs/xiaohongshu:abc123").status_code == 200
    assert c.delete("/api/v2/trend-refs/xiaohongshu:abc123").status_code == 404
    assert len(c.get("/api/v2/trend-refs").json()) == 1


def test_trend_refs_rejects_bad_items(tmp_path):
    c = TestClient(create_app({}, tmp_path / "out", tmp_path / "up"))
    bad = [
        item("../etc"),                                  # 이상한 id
        item("ok1", url="javascript:alert(1)"),          # https 가 아닌 링크
        item("ok2", platform="facebook"),                # 지원하지 않는 플랫폼
        "not a dict",
    ]
    r = c.post("/api/v2/trend-refs", json={"items": bad + [item("ok3", score=500, likes="많음")]})
    assert r.json() == {"added": 1, "updated": 0, "skipped": 4, "total": 1}
    row = c.get("/api/v2/trend-refs").json()[0]
    assert row["score"] == 100 and row["likes"] is None    # 범위·형식 정리
    assert c.post("/api/v2/trend-refs", json={"items": [item(f"x{i}") for i in range(501)]}).status_code == 400


def test_trend_refs_need_login_when_locked(tmp_path):
    c = TestClient(create_app({}, tmp_path / "out", tmp_path / "up", access_code="secret1"), follow_redirects=False)
    assert c.post("/api/v2/trend-refs", json={"items": [item()]}).status_code == 401
    r = c.post("/api/v2/trend-refs", json={"items": [item()]}, headers={"Authorization": "Bearer secret1"})
    assert r.status_code == 200 and r.json()["added"] == 1
