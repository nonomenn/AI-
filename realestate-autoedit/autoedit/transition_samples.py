"""トランジションの見比べ用動画。同じ2カットを、トランジションだけ変えて順に並べる。

  python -m autoedit.transition_samples 物件動画/物件名            # 出力/トランジション比較.mp4
  python -m autoedit.transition_samples 物件動画/物件名 --types light_leak,soft_wipe

2カットは、直近の構成表(出力/*_plan.json)で隣り合う別の部屋のカットを使う。
気に入ったものを style.yaml の transitions(room_change / same_room)に設定する。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

from .analyze import Segment
from .fonts import resolve_fonts
from .media import probe
from .planner import Shot
from .project import open_project
from .render import TRANSITION_NAMES, ShotSource, _transition, _zoomed

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pick_pair(plan_json: str):
    with open(plan_json, encoding="utf-8") as f:
        plan = [p for p in json.load(f)["plan"] if p["section"] == "rooms"]
    for a, b in zip(plan, plan[1:]):
        if a["room"] != b["room"]:
            return a, b
    raise SystemExit("構成表に、隣り合う別の部屋のカットがありません")


def _shot(p, dur):
    pr = probe(p["clip"])
    seg = Segment(clip=p["clip"], start=p["src_start"], end=p["src_start"] + 30, fps=pr.fps,
                  width=pr.width, height=pr.height, room=p["room"])
    interp = "blend" if p["speed"] < 1 and pr.fps < 50 else ""
    return Shot(section="rooms", seg=seg, src_start=p["src_start"], duration=dur, speed=p["speed"],
                room=p["room"], interp=interp)


def _label_img(text, font_path, W):
    f = ImageFont.truetype(font_path, 44)
    im = Image.new("RGBA", (W, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 120), fill=(0, 0, 0, 150))
    d.text((W / 2, 60), text, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return np.asarray(im).astype(np.float32) / 255.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="トランジションの見比べ用動画")
    ap.add_argument("project")
    ap.add_argument("--types", default=",".join(TRANSITION_NAMES), help="並べる種類(カンマ区切り)")
    ap.add_argument("--duration", type=float, default=1.1, help="トランジションの長さ(秒)")
    args = ap.parse_args(argv)
    pj = open_project(args.project)
    jsons = sorted(glob.glob(os.path.join(pj.out_dir, "*_plan.json")), key=os.path.getmtime)
    if not jsons:
        raise SystemExit("先に python -m autoedit 物件フォルダ --plan-only で構成表を作ってください")
    a, b = _pick_pair(jsons[-1])
    with open(os.path.join(HERE, "config/style.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    fonts = resolve_fonts(cfg["fonts"], pj.font_dir, log=lambda *_: None)
    W, H, fps = cfg["canvas"]["width"], cfg["canvas"]["height"], cfg["canvas"]["fps"]
    z0, z1 = cfg["motion"]["push_in"]
    hold, td = 2.0, args.duration
    shot_len = hold + td
    out = os.path.join(pj.out_dir, "トランジション比較.mp4")
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    for k, kind in enumerate(types):
        label = _label_img(f"{k + 1}. {TRANSITION_NAMES.get(kind, kind)}", fonts["sans_bold"], W)
        sa, sb = ShotSource(_shot(a, shot_len), W, H), ShotSource(_shot(b, shot_len), W, H)
        total = shot_len * 2 - td
        for fi in range(int(total * fps)):
            t = fi / fps
            fa = fb = None
            if t < shot_len:
                src = sa.get(t)
                fa = _zoomed(src, W, H, (z0 + (z1 - z0) * t / shot_len) / sa.cw * W)
            if t >= hold:
                u = t - hold
                src = sb.get(u)
                fb = _zoomed(src, W, H, (z0 + (z1 - z0) * u / shot_len) / sb.cw * W)
            if fa is not None and fb is not None:
                frame = _transition(fa, fb, kind, (t - hold) / td)
            else:
                frame = fa if fa is not None else fb
            frame = np.ascontiguousarray(frame).astype(np.float32)
            al = label[..., 3:4]
            frame[140:260] = frame[140:260] * (1 - al) + label[..., 2::-1] * 255 * al
            enc.stdin.write(frame.astype(np.uint8).tobytes())
        sa.close()
        sb.close()
        print(f"  {k + 1}. {TRANSITION_NAMES.get(kind, kind)}")
    enc.stdin.close()
    enc.wait()
    print(out)


if __name__ == "__main__":
    main()
