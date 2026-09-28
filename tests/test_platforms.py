import pytest

from shortsmaker.platforms import PostMeta, publish_all
from shortsmaker.platforms.instagram import InstagramPublisher
from shortsmaker.platforms.threads import ThreadsPublisher
from shortsmaker.platforms.tiktok import TikTokPublisher, chunk_plan

from conftest import FakeResponse, FakeSession

META = PostMeta("오늘의 영상", "설명입니다", ["여행", "#브이로그", "여행"])


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "short.mp4"
    p.write_bytes(b"0" * 1000)
    return p


def test_caption_dedupes_tags_and_truncates():
    assert META.caption(1000) == "오늘의 영상\n\n설명입니다\n\n#여행 #브이로그"
    assert len(META.caption(5)) == 5


def test_instagram_resumable_upload(video):
    polls = iter(["IN_PROGRESS", "FINISHED"])

    def handler(method, url, kw):
        if url.endswith("/123/media"):
            assert kw["params"]["upload_type"] == "resumable"
            assert kw["params"]["media_type"] == "REELS"
            return FakeResponse({"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v21.0/C1"})
        if "rupload" in url:
            assert kw["headers"]["file_size"] == "1000"
            assert kw["data"] == b"0" * 1000
            return FakeResponse({"success": True})
        if url.endswith("/C1"):
            return FakeResponse({"status_code": next(polls)})
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "M1"})
        if url.endswith("/M1"):
            return FakeResponse({"permalink": "https://instagram.com/reel/x"})
        raise AssertionError(url)

    s = FakeSession(handler)
    r = InstagramPublisher({"access_token": "t", "user_id": "123"}, session=s, sleep=lambda _: None).publish(video, META)
    assert r.ok and r.post_id == "M1" and r.url == "https://instagram.com/reel/x"


def test_instagram_uses_public_url(video):
    def handler(method, url, kw):
        if url.endswith("/123/media"):
            assert kw["params"]["video_url"] == "https://cdn.example.com/v/short.mp4"
            return FakeResponse({"id": "C1"})
        if url.endswith("/C1"):
            return FakeResponse({"status_code": "FINISHED"})
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "M1"})
        return FakeResponse({})

    s = FakeSession(handler)
    InstagramPublisher({"access_token": "t", "user_id": "123"}, public_base_url="https://cdn.example.com/v/",
                       session=s, sleep=lambda _: None).publish(video, META)
    assert not any("rupload" in c[1] for c in s.calls)


def test_threads_requires_public_url(video):
    res = publish_all(video, META, ["threads"], {"threads": {"access_token": "t", "user_id": "u"}})
    assert not res[0].ok and "공개 URL" in res[0].error


def test_threads_flow(video):
    def handler(method, url, kw):
        if url.endswith("/u/threads"):
            assert kw["params"]["media_type"] == "VIDEO"
            assert len(kw["params"]["text"]) <= 500
            return FakeResponse({"id": "C"})
        if url.endswith("/C"):
            return FakeResponse({"status": "FINISHED"})
        if url.endswith("/threads_publish"):
            return FakeResponse({"id": "P"})
        return FakeResponse({"permalink": "https://threads.net/p"})

    r = ThreadsPublisher({"access_token": "t", "user_id": "u"}, public_base_url="https://x.com/o",
                         session=FakeSession(handler), sleep=lambda _: None).publish(video, META)
    assert r.ok and r.url == "https://threads.net/p"


def test_tiktok_chunk_plan():
    assert chunk_plan(1000) == (1000, 1)
    size = 100 * 1024 * 1024 + 123
    cs, n = chunk_plan(size)
    assert cs == 10 * 1024 * 1024 and n == 10  # 마지막 청크가 나머지 흡수


def test_tiktok_flow(video):
    def handler(method, url, kw):
        if url.endswith("/video/init/"):
            assert kw["json"]["source_info"]["video_size"] == 1000
            return FakeResponse({"data": {"publish_id": "P", "upload_url": "https://up"}, "error": {"code": "ok"}})
        if url == "https://up":
            assert kw["headers"]["Content-Range"] == "bytes 0-999/1000"
            return FakeResponse(status=201, content=b"")
        if url.endswith("/status/fetch/"):
            return FakeResponse({"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok"}})
        raise AssertionError(url)

    r = TikTokPublisher({"access_token": "t"}, session=FakeSession(handler), sleep=lambda _: None).publish(video, META)
    assert r.ok and r.post_id == "P"


def test_publish_all_collects_errors(video):
    res = publish_all(video, META, ["instagram", "myspace"], {})
    assert [r.ok for r in res] == [False, False]
    assert "access_token" in res[0].error
