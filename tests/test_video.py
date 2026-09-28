import re
import subprocess

from shortsmaker.video import VideoOptions, ffmpeg_exe, make_video, plan_timeline


def probe(path):
    err = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    size = re.search(r"Video: h264.*?, (\d+)x(\d+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s), tuple(map(int, size)), "Audio: aac" in err


def test_plan_timeline_basic():
    d, t, total = plan_timeline(3, VideoOptions(seconds_per_image=3, transition=0.5))
    assert (d, t) == (3, 0.5)
    assert total == 8


def test_plan_timeline_caps_duration():
    d, t, total = plan_timeline(40, VideoOptions(seconds_per_image=3, transition=0.5, max_duration=60))
    assert total == 60
    assert abs(40 * d - 39 * t - 60) < 1e-6


def test_make_video(photos, tmp_path):
    out = tmp_path / "out.mp4"
    opts = VideoOptions(width=216, height=384, fps=10, seconds_per_image=1.0, transition=0.3,
                        title="제목", captions=["하나", "둘"], preset="ultrafast")
    make_video(photos, out, opts)
    duration, size, has_audio = probe(out)
    assert size == (216, 384)
    assert abs(duration - 2.4) < 0.2
    assert has_audio


def test_make_video_no_kenburns_crop(photos, tmp_path):
    out = tmp_path / "out.mp4"
    opts = VideoOptions(width=216, height=384, fps=10, seconds_per_image=0.5, transition=0,
                        ken_burns=False, fit="crop", preset="ultrafast")
    make_video(photos[:1], out, opts)
    assert out.stat().st_size > 0
