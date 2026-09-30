"""確認用: 書き出した動画の1コマに、TikTokのUI位置(アカウントアイコン・右側ボタン・下部キャプション)のガイドを重ねる。
CTAの矢印がアカウントアイコンを正しく指しているかを、投稿前に確認するために使う。

  python -m autoedit.preview out/demo.mp4 --out out/cta_check.png          # --t 省略時は最後から1秒前(CTA)
"""
from __future__ import annotations

import argparse
import os
import subprocess

import yaml
from PIL import Image, ImageDraw, ImageFont

from .fonts import resolve_fonts
from .media import probe

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw_guides(im: Image.Image, cfg: dict) -> Image.Image:
    a = cfg["telops"]["cta"]["arrow"]
    tx, ty = a["target"]
    r = a["target_radius"]
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    W, H = im.size
    # 下部キャプション領域・右側ボタン列(目安)
    d.rectangle((0, int(H * 0.80), W, H), fill=(255, 0, 80, 50))
    d.rectangle((int(W * 0.86), int(H * 0.44), W, int(H * 0.80)), fill=(255, 0, 80, 40))
    # アカウントアイコン(推定位置)
    d.ellipse((tx - r, ty - r, tx + r, ty + r), fill=(255, 255, 255, 170), outline=(255, 40, 90, 255), width=5)
    font = ImageFont.truetype(resolve_fonts({"s": cfg["fonts"]["sans_bold"]}, log=lambda *_: None)["s"], 26)
    d.text((tx - r - 10, ty + r + 10), "アイコン", font=font, fill=(255, 40, 90, 255))
    # 右側のいいね等(目安)
    for k in range(4):
        cy = ty + 140 + k * 130
        d.ellipse((tx - 34, cy - 34, tx + 34, cy + 34), outline=(255, 255, 255, 160), width=4)
    return Image.alpha_composite(im.convert("RGBA"), ov)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--t", type=float, help="確認する時刻(秒)。省略時は最後から1秒前")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(os.path.join(HERE, "config/style.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    t = args.t if args.t is not None else max(0.0, probe(args.video).duration - 1.0)
    tmp = args.out + ".raw.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", args.video, "-frames:v", "1", tmp], check=True)
    draw_guides(Image.open(tmp), cfg).convert("RGB").save(args.out)
    os.remove(tmp)
    print(args.out)


if __name__ == "__main__":
    main()
