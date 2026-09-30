import subprocess

from autoedit.analyze import analyze_clip
from autoedit.media import grab_frame, probe
from conftest import make_clip


def test_probe_rotation(tmp_path):
    land = tmp_path / "l.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1",
                    "-c:v", "libx264", "-preset", "ultrafast", str(land)], check=True)
    rot = tmp_path / "日本語_縦.mp4"  # 日本語パスも読めること
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", str(land), "-c", "copy",
                    str(rot)], check=True)
    p = probe(str(rot))
    assert (p.width, p.height) == (180, 320) and p.portrait
    assert grab_frame(str(rot), 0.5).shape == (320, 180, 3)
    assert not probe(str(land)).portrait


def test_slow_pan_is_usable(tmp_path, cfg):
    clip = make_clip(str(tmp_path / "living_01.mp4"), seconds=4, speed_px=60)  # 0.11画面幅/秒
    segs, dbg = analyze_clip(clip, cfg)
    assert segs, "ゆっくりした横移動は使える区間になる"
    assert sum(s.duration for s in segs) > 3.0
    assert segs[0].fps == 60 and segs[0].height > segs[0].width


def test_fast_pan_is_dropped(tmp_path, cfg):
    clip = make_clip(str(tmp_path / "fast.mp4"), seconds=3, speed_px=700)  # 1.3画面幅/秒
    segs, _ = analyze_clip(clip, cfg)
    assert sum(s.duration for s in segs) < 0.5
