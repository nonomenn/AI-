import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def make_clip(path, seconds=4.0, speed_px=60, fps=60, size=(540, 960)):
    """クリップごとに違う模様を、ゆっくり横に流した縦長クリップ(speed_px: 1秒あたりの移動px)。
    模様はファイル名から決まる乱数で作る(同じ模様だと「同じ映像」とみなされて2回使われないため)。"""
    import zlib

    import cv2
    import numpy as np
    w, h = size
    src_w = w + int(speed_px * seconds) + 40
    rng = np.random.default_rng(zlib.crc32(os.path.basename(path).encode()))
    tex = cv2.resize((rng.random((h // 8, src_w // 8, 3)) * 255).astype(np.uint8), (src_w, h),
                     interpolation=cv2.INTER_CUBIC)
    tex = cv2.addWeighted(tex, 0.7, (rng.random((h, src_w, 3)) * 255).astype(np.uint8), 0.3, 0)
    png = path + ".tex.png"
    cv2.imwrite(png, tex)
    vf = f"crop={w}:{h}:x='min({src_w - w},t*{speed_px})':y=0"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps), "-t", str(seconds),
                    "-i", png, "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path],
                   check=True)
    os.remove(png)
    return path


@pytest.fixture(scope="session")
def cfg():
    with open(os.path.join(ROOT, "config/style.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def tpl():
    with open(os.path.join(ROOT, "config/template.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


class FakeClient:
    """anthropic.Anthropic の代わり。responder(content) → dict を JSON で返す。"""

    def __init__(self, responder, stop_reason="end_turn"):
        self.calls = []
        self.responder = responder
        self.stop_reason = stop_reason
        outer = self

        class _Msgs:
            def create(self, **kw):
                outer.calls.append(kw)
                data = outer.responder(kw["messages"][0]["content"])
                return SimpleNamespace(stop_reason=outer.stop_reason,
                                       content=[SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))])

        self.messages = _Msgs()
        self.beta = SimpleNamespace(messages=_Msgs())


@pytest.fixture
def fake_client():
    return FakeClient
