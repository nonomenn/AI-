"""動画の読み込み(ffprobe / ffmpeg 経由)。

OpenCV の VideoCapture は Windows で日本語パス(物件動画/…)を開けないことがあり、
スマホ縦撮りの回転メタデータの扱いも環境で揺れるため、読み込みは ffmpeg に統一する。
ffmpeg は回転メタデータを自動で適用するので、ここで返す幅・高さは「見た目どおり」の向き。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np


class MediaError(RuntimeError):
    pass


def require_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
    if missing:
        raise MediaError(f"{' と '.join(missing)} が見つかりません。ffmpeg をインストールして PATH を通してください")


@dataclass
class Probe:
    width: int          # 回転適用後
    height: int
    fps: float
    duration: float
    rotation: int = 0

    @property
    def portrait(self) -> bool:
        return self.height >= self.width


def _rate(s: str | None) -> float:
    if not s or s in ("0/0", "0"):
        return 0.0
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else 0.0
    return float(s)


def probe(path: str) -> Probe:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format",
                        "-of", "json", path], capture_output=True)
    if r.returncode != 0:
        raise MediaError(f"動画を読めません: {path}\n{r.stderr.decode(errors='replace')[:300]}")
    info = json.loads(r.stdout.decode("utf-8", errors="replace"))
    if not info.get("streams"):
        raise MediaError(f"映像トラックがありません: {path}")
    st = info["streams"][0]
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(round(float(sd["rotation"])))
    if not rot and st.get("tags", {}).get("rotate"):
        rot = int(st["tags"]["rotate"])
    w, h = int(st["width"]), int(st["height"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    fps = _rate(st.get("avg_frame_rate")) or _rate(st.get("r_frame_rate")) or 30.0
    dur = float(st.get("duration") or info.get("format", {}).get("duration") or 0.0)
    return Probe(w, h, fps, dur, rot)


def gray_frames(path: str, sample_hz: float, width: int = 320):
    """sample_hz で間引いたグレースケール画像(幅 width)を順に返す。i 番目の時刻は i / sample_hz。"""
    p = probe(path)
    height = int(round(width * p.height / p.width / 2)) * 2
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-an", "-vf",
           f"fps={sample_hz},scale={width}:{height}:flags=area", "-pix_fmt", "gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)
    n = width * height
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(height, width)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def grab_frame(path: str, t: float, width: int | None = None):
    """時刻 t(秒)の1コマ(BGR)。取れなければ None。"""
    p = probe(path)
    w = width or p.width
    h = int(round(w * p.height / p.width / 2)) * 2
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1", "-an",
           "-vf", f"scale={w}:{h}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or len(r.stdout) < w * h * 3:
        return None
    return np.frombuffer(r.stdout[: w * h * 3], np.uint8).reshape(h, w, 3).copy()
