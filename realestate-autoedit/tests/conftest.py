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
    """テストパターンをゆっくり横に流した縦長クリップ(speed_px: 1秒あたりの移動px)。"""
    w, h = size
    src_w = w + int(speed_px * seconds) + 40
    vf = f"crop={w}:{h}:x='min({src_w - w},t*{speed_px})':y=0"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
           f"testsrc2=size={src_w}x{h}:rate={fps}:duration={seconds}", "-vf", vf,
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    subprocess.run(cmd + [path], check=True)
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
