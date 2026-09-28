import pytest

from shortsmaker.sources import resolve_inputs, youtube_video_id

from conftest import FakeResponse, FakeSession


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
])
def test_youtube_video_id(url):
    assert youtube_video_id(url) == "dQw4w9WgXcQ"


def test_resolve_keeps_order_and_falls_back_thumbnail(photos, tmp_path):
    def handler(method, url, kw):
        if "maxresdefault" in url:
            return FakeResponse(status=404, content=b"")
        return FakeResponse(status=200, content=b"x" * 5000)

    session = FakeSession(handler)
    folder = photos[0].parent
    out = resolve_inputs([str(photos[2]), "https://youtu.be/dQw4w9WgXcQ"], tmp_path / "w", session)
    assert out[0] == photos[2]
    assert out[1].name.endswith("dQw4w9WgXcQ.jpg")
    assert any("sddefault" in c[1] for c in session.calls)
    assert resolve_inputs([str(folder)], tmp_path / "w2") == sorted(photos)


def test_resolve_missing():
    with pytest.raises(FileNotFoundError):
        resolve_inputs(["nope.jpg"])
