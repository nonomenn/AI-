"""カット確認シート: 使った各カットの「始め・中・終わり」のコマを並べ、付けた部屋名・テロップを書き込んだ画像。

部屋名テロップと映像が合っているか(廊下のカットに「Powder room」が付いていないか等)を、投稿前に一目で確認するためのもの。
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .media import grab_frame

TILE_W = 180


def _label(shot, copy, props) -> str:
    if shot.telop == "room":
        r = (props.get("rooms") or {}).get(shot.room) or copy["rooms"].get(shot.room) or {}
        return f"テロップ「{r.get('title', '')}」"
    if shot.telop:
        return f"テロップ: {shot.telop}"
    return ""


def cut_sheet(plan, starts, copy: dict, props: dict, font_path: str, out_path: str) -> str:
    font = ImageFont.truetype(font_path, 22)
    rows = []
    for st, p in zip(starts, plan):
        if not p.seg:
            continue
        src_len = p.duration * p.speed
        tiles = []
        for t in (p.src_start + 0.05, p.src_start + src_len / 2, p.src_start + src_len - 0.05):
            f = grab_frame(p.seg.clip, t, width=TILE_W)
            if f is None:
                f = np.zeros((int(TILE_W * 16 / 9), TILE_W, 3), np.uint8)
            tiles.append(f)
        h = max(t.shape[0] for t in tiles)
        strip = np.hstack([cv2.resize(t, (TILE_W, h)) for t in tiles])
        im = Image.fromarray(cv2.cvtColor(strip, cv2.COLOR_BGR2RGB))
        info = Image.new("RGB", (420, h), (24, 24, 24))
        d = ImageDraw.Draw(info)
        lines = [f"{st:5.1f}s  {p.section}", f"部屋: {p.room}", _label(p, copy, props),
                 f"{p.seg.id}", f"素材 {p.src_start:.1f}〜{p.src_start + src_len:.1f}s", f"映え {p.seg.beauty:.0f}  {p.seg.note}"]
        for k, ln in enumerate(lines):
            d.text((14, 14 + k * 34), ln, font=font, fill=(255, 220, 140) if k in (1, 2) else (230, 230, 230))
        row = Image.new("RGB", (im.width + info.width, h))
        row.paste(im, (0, 0))
        row.paste(info, (im.width, 0))
        rows.append(row)
    if not rows:
        return ""
    sheet = Image.new("RGB", (rows[0].width, sum(r.height + 6 for r in rows)), (60, 60, 60))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 6
    sheet.save(out_path, quality=88)
    return out_path
