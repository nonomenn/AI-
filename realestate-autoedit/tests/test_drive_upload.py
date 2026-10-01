"""ドライブ保存(Apps Script への送信)。本物の Google には送らず、手元の偽サーバーで確認する。"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from urllib.parse import quote

import pytest

from autoedit import drive_upload

received = []


class FakeAppsScript(BaseHTTPRequestHandler):
    def do_POST(self):  # Apps Script と同じく、結果は別URLへのリダイレクトで返す
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        received.append(body)
        ok = body["key"] == "secret"
        self.send_response(302)
        self.send_header("Location", f"/result?ok={int(ok)}&name={quote(body['name'])}")
        self.end_headers()

    def do_GET(self):
        ok = "ok=1" in self.path
        res = {"ok": ok, "id": "x", "url": "u", "folder": "https://drive/f"} if ok else {"ok": False, "error": "key"}
        data = json.dumps(res).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), FakeAppsScript)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    received.clear()
    yield f"http://127.0.0.1:{srv.server_port}/exec"
    srv.shutdown()


def test_upload_folder(tmp_path, server, monkeypatch):
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.delenv(k, raising=False)
    d = tmp_path / "No.L036_テスト"
    d.mkdir()
    (d / "No.L036_テスト_キャプション.txt").write_text("No.L036", encoding="utf-8")
    (d / "No.L036_テスト.mp4").write_bytes(b"\x00\x01video")
    res = drive_upload.upload_folder(str(d), url=server, key="secret", log=lambda *_: None)
    assert len(res) == 2 and all(r["ok"] for r in res)
    names = {r["name"]: r for r in received}
    assert names["No.L036_テスト.mp4"]["folder"] == "No.L036_テスト"
    assert names["No.L036_テスト.mp4"]["mime"] == "video/mp4"
    assert base64.b64decode(names["No.L036_テスト.mp4"]["data"]) == b"\x00\x01video"


def test_wrong_key(tmp_path, server, monkeypatch):
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(drive_upload.DriveUploadError, match="KEY"):
        drive_upload.upload_file(str(f), "F", url=server, key="wrong")
