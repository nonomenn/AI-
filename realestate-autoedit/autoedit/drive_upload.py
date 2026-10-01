"""完成品(動画・サムネ・キャプション)を Google ドライブへ保存する。

仕組み: 自分の Google アカウントに置いた Apps Script(tools/drive_upload.gs)にファイルを送る。
ドライブのパスワードや認証情報をこのツールに渡さずに済み、合言葉(KEY)を知っている人だけが保存できる。

設定(環境変数):
  AUTOEDIT_DRIVE_URL  Apps Script をウェブアプリとして公開したときの URL(https://script.google.com/macros/s/…/exec)
  AUTOEDIT_DRIVE_KEY  drive_upload.gs の KEY と同じ文字列

  python -m autoedit.drive_upload 物件動画/完成/No.L036_物件名     # フォルダの中身を手動で送る
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import urllib.request

MAX_MB = 35  # Apps Script が一度に受け取れる大きさ(base64 で約50MB)に余裕を持たせる


class DriveUploadError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("AUTOEDIT_DRIVE_URL") and os.environ.get("AUTOEDIT_DRIVE_KEY"))


def upload_file(path: str, folder: str, url: str | None = None, key: str | None = None, opener=None) -> dict:
    url = url or os.environ["AUTOEDIT_DRIVE_URL"]
    key = key or os.environ["AUTOEDIT_DRIVE_KEY"]
    size = os.path.getsize(path) / 1e6
    if size > MAX_MB:
        raise DriveUploadError(f"{os.path.basename(path)} が {size:.0f}MB あり、一度に送れる上限({MAX_MB}MB)を超えています")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    body = json.dumps({"key": key, "folder": folder, "name": os.path.basename(path), "mime": mime,
                       "data": data}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    # Apps Script は結果を別のURLへのリダイレクトで返す。urllib は POST→GET に切り替えて追いかける
    with (opener or urllib.request.urlopen)(req, timeout=600) as r:
        res = json.loads(r.read().decode("utf-8", errors="replace"))
    if not res.get("ok"):
        raise DriveUploadError(f"ドライブへの保存に失敗: {res.get('error')}"
                               + ("(KEY が Apps Script と一致していません)" if res.get("error") == "key" else ""))
    return res


def upload_folder(local_dir: str, log=print, **kw) -> list[dict]:
    """完成フォルダの中身を、ドライブの 完成動画/<同じフォルダ名>/ に保存する。"""
    folder = os.path.basename(os.path.normpath(local_dir))
    out = []
    for name in sorted(os.listdir(local_dir)):
        p = os.path.join(local_dir, name)
        if os.path.isfile(p):
            res = upload_file(p, folder, **kw)
            log(f"  ドライブに保存: 完成動画/{folder}/{name}")
            out.append(res)
    if out and out[-1].get("folder"):
        log(f"  {out[-1]['folder']}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("使い方: python -m autoedit.drive_upload 物件動画/完成/No.L036_物件名")
    if not configured():
        sys.exit("AUTOEDIT_DRIVE_URL と AUTOEDIT_DRIVE_KEY を設定してください(README の「ドライブに自動保存」)")
    upload_folder(sys.argv[1])
