import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SHORTSMAKER_PROBE_CREDENTIALS", "0")   # 테스트는 네트워크 감지를 하지 않는다


@pytest.fixture
def photos(tmp_path):
    paths = []
    for i, (color, size) in enumerate([("red", (320, 180)), ("green", (180, 320)), ("blue", (200, 200))]):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", size, color).save(p)
        paths.append(p)
    return paths


class FakeResponse:
    def __init__(self, data=None, status=200, content=None):
        self._data = data
        self.status_code = status
        self.content = content if content is not None else (b"{}" if data is not None else b"")
        self.text = str(data)

    def json(self):
        return self._data


class FakeSession:
    """requests.Session 대역: 호출을 기록하고 handler(method, url, kwargs) 결과를 돌려준다."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.handler(method, url, kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        if hasattr(kw.get("data"), "read"):
            kw["data"] = kw["data"].read()
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)
