"""テロップの描画(Pillow)とアニメーション定義。

現状のTOALU動画から採寸したデザインを再現:
  hook  … 極太明朝・白・斜体・黒のドロップシャドウ
  catch … 同上 2行 + 強調語の上に傍点(●)
  start … 「ルームツアー START」字間広め・斜体・左へ流れる
  room  … 英字セリフの部屋名 + 明朝のサブコピー、ふわっとフェードイン
  cta   … 白枠+半透明の黒ボックス、斜体ゴシック、✓アイコン + アカウントアイコンを指す矢印
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 2  # 描画時のスーパーサンプリング倍率(アンチエイリアス用)


@dataclass
class Layer:
    img: np.ndarray                  # RGBA float32 (0-1), premultiplied ではない
    x: float                         # 左上の座標(キャンバス座標)
    y: float
    anim: Callable[[float, float], tuple[float, float, float]]  # (t, dur) -> (alpha, dx, dy)


def _font(path, size):
    return ImageFont.truetype(path, size, index=0)


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def fade_anim(fade_in, fade_out, rise=0.0, delay=0.0):
    def f(t, dur):
        t2 = t - delay
        if t2 < 0:
            return 0.0, 0.0, 0.0
        a_in = _ease(t2 / fade_in) if fade_in > 0 else 1.0
        a_out = _ease((dur - t) / fade_out) if fade_out > 0 else 1.0
        dy = rise * (1 - a_in)
        return min(a_in, a_out), 0.0, dy
    return f


def _to_layer(im: Image.Image, cx: float, cy: float, anim) -> Layer:
    if SS != 1:
        im = im.resize((max(1, im.width // SS), max(1, im.height // SS)), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32) / 255.0
    return Layer(arr, cx - im.width / 2, cy - im.height / 2, anim)


def _skew(im: Image.Image, k: float) -> Image.Image:
    if not k:
        return im
    w, h = im.size
    extra = int(abs(k) * h) + 2
    return im.transform((w + extra, h), Image.AFFINE, (1, k, -k * h, 0, 1, 0), resample=Image.BICUBIC)


def _shadowed(text_img: Image.Image, shadow: dict | None) -> Image.Image:
    """テキスト(RGBA)にドロップシャドウを付けて返す。"""
    if not shadow:
        return text_img
    ox, oy = [int(v * SS) for v in shadow["offset"]]
    blur = shadow.get("blur", 0) * SS
    pad = int(abs(ox) + abs(oy) + blur * 3 + 4)
    w, h = text_img.size
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    a = text_img.split()[3]
    sh = Image.new("RGBA", text_img.size, tuple(shadow["color"]) + (0,))
    sh.putalpha(a.point(lambda v: int(v * shadow.get("opacity", 0.8))))
    sh_canvas = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh_canvas.paste(sh, (pad + ox, pad + oy), sh)
    if blur:
        sh_canvas = sh_canvas.filter(ImageFilter.GaussianBlur(blur))
    out = Image.alpha_composite(out, sh_canvas)
    out.alpha_composite(text_img, (pad, pad))
    return out


def _text_lines(lines, font, color, spacing=1.2, letter_spacing=0, dots: list[list[int]] | None = None,
                dot_cfg: dict | None = None) -> Image.Image:
    """複数行のテキストを中央揃えで描画。spacing=行送り(文字サイズ比)。dots=各行の傍点を付ける文字インデックス。"""
    def line_w(s):
        if letter_spacing:
            return sum(font.getlength(c) for c in s) + letter_spacing * SS * (len(s) - 1)
        return font.getlength(s)

    em = font.size
    top = font.getbbox("国")[1]                 # 描画原点から字面の上端までの距離
    asc, desc = font.getmetrics()
    lh = int(em * spacing)
    r = dot_cfg["radius"] * SS if dot_cfg else 0
    dot_space = int(r * 2 + dot_cfg["gap_above"] * SS) if dots and any(dots) else 0
    W = int(max(line_w(s) for s in lines)) + 8 * SS
    H = dot_space + lh * (len(lines) - 1) + asc + desc + 8 * SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = dot_space + 4 * SS - top
    for li, s in enumerate(lines):
        x = (W - line_w(s)) / 2
        xs = []
        for c in s:
            xs.append(x)
            d.text((x, y), c, font=font, fill=tuple(color) + (255,))
            x += font.getlength(c) + letter_spacing * SS
        if dots and li < len(dots):
            for ci in dots[li]:
                cx = xs[ci] + font.getlength(s[ci]) / 2
                cy = y + top - dot_cfg["gap_above"] * SS - r
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(color) + (255,))
        y += lh
    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im


def _parse_emphasis(text: str):
    """「《阿波座駅》3分の」→ 表示文字列と傍点インデックス。"""
    lines, dots = [], []
    for raw in text.split("\n"):
        out, idx, on = "", [], False
        for ch in raw:
            if ch == "《":
                on = True; continue
            if ch == "》":
                on = False; continue
            if on:
                idx.append(len(out))
            out += ch
        lines.append(out); dots.append(idx)
    return lines, dots


# ------------------------------------------------------------------ 各テロップ
def make_hook(text, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["hook"]
    size = c["size"]
    font = _font(fonts[c["font"]], size * SS)
    while font.getlength(text) > c["max_width"] * SS and size > 40:
        size -= 2
        font = _font(fonts[c["font"]], size * SS)
    im = _text_lines([text], font, c["color"])
    im = _shadowed(_skew(im, c["italic_skew"]), c["shadow"])
    return [_to_layer(im, cfg["canvas"]["width"] / 2, c["center_y"], fade_anim(c["fade_in"], c["fade_out"]))]


def make_catch(text, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["catch"]
    lines, dots = _parse_emphasis(text)
    size = c["size"]
    font = _font(fonts[c["font"]], size * SS)
    while max(font.getlength(s) for s in lines) > c["max_width"] * SS and size > 40:
        size -= 2
        font = _font(fonts[c["font"]], size * SS)
    im = _text_lines(lines, font, c["color"], c["line_spacing"], dots=dots, dot_cfg=c["emphasis_dot"])
    im = _shadowed(_skew(im, c["italic_skew"]), c["shadow"])
    return [_to_layer(im, cfg["canvas"]["width"] / 2, c["center_y"], fade_anim(c["fade_in"], c["fade_out"]))]


def make_start(text, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["start"]
    font = _font(fonts[c["font"]], c["size"] * SS)
    im = _text_lines([text], font, c["color"], letter_spacing=c["letter_spacing"])
    im = _shadowed(_skew(im, c["italic_skew"]), c["shadow"])
    x0, x1 = c["move_from_x"], c["move_to_x"]

    def anim(t, dur):
        a, _, _ = fade_anim(c["fade_in"], c["fade_out"])(t, dur)
        p = t / dur if dur else 1
        return a, x0 + (x1 - x0) * p, 0.0
    return [_to_layer(im, cfg["canvas"]["width"] / 2, c["center_y"], anim)]


def make_room(title, sub, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["room"]
    tf = _font(fonts[c["title_font"]], c["title_size"] * SS)
    sf = _font(fonts[c["sub_font"]], c["sub_size"] * SS)
    t_im = _text_lines([title], tf, c["color"])
    s_im = _text_lines([sub], sf, c["color"]) if sub else None
    gap = c["sub_gap"] * SS
    W = max(t_im.width, s_im.width if s_im else 0)
    H = t_im.height + (gap + s_im.height if s_im else 0)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(t_im, ((W - t_im.width) // 2, 0))
    if s_im:
        im.alpha_composite(s_im, ((W - s_im.width) // 2, t_im.height + gap))
    im = _shadowed(im, c["shadow"])
    # center_y はタイトル行の中心 → ブロック全体の中心に換算
    cy = c["center_y"] - t_im.height / SS / 2 + im.height / SS / 2
    return [_to_layer(im, cfg["canvas"]["width"] / 2, cy,
                      fade_anim(c["fade_in"], c["fade_out"], rise=c["rise"], delay=c["delay"]))]


def _check_icon(size_px, color) -> Image.Image:
    im = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, size_px - 1, size_px - 1), fill=tuple(color) + (255,))
    w = max(2, size_px // 8)
    pts = [(size_px * 0.27, size_px * 0.52), (size_px * 0.44, size_px * 0.68), (size_px * 0.74, size_px * 0.34)]
    d.line(pts, fill=(55, 55, 55, 255), width=w, joint="curve")
    return im


def make_cta(text, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["cta"]
    font = _font(fonts[c["font"]], c["size"] * SS)
    t_im = _text_lines([text], font, c["color"])
    if c.get("check_icon"):
        ic = _check_icon(int(c["size"] * 0.82 * SS), c["color"])
        comb = Image.new("RGBA", (t_im.width + ic.width + 8 * SS, max(t_im.height, ic.height)), (0, 0, 0, 0))
        comb.alpha_composite(t_im, (0, (comb.height - t_im.height) // 2))
        comb.alpha_composite(ic, (t_im.width + 8 * SS, (comb.height - ic.height) // 2))
        t_im = comb
    t_im = _skew(t_im, c["italic_skew"])
    b = c["box"]
    px, py, bw = b["pad_x"] * SS, b["pad_y"] * SS, b["border"] * SS
    box = Image.new("RGBA", (t_im.width + 2 * px, t_im.height + 2 * py), (0, 0, 0, 0))
    d = ImageDraw.Draw(box)
    d.rectangle((0, 0, box.width - 1, box.height - 1), fill=tuple(b["fill"]) + (int(255 * b["fill_opacity"]),),
                outline=tuple(b["border_color"]) + (255,), width=bw)
    box.alpha_composite(t_im, (px, py))
    layers = [_to_layer(box, c["center_x"], c["center_y"], fade_anim(c["fade_in"], 0.0))]
    layers.append(make_arrow(cfg))
    return layers


def arrow_geometry(cfg):
    """矢印の始点・先端を計算。先端はアカウントアイコン中心へ向かい、縁の手前 gap px で止まる。"""
    a = cfg["telops"]["cta"]["arrow"]
    tx, ty = a["target"]
    ang = math.radians(a["angle_deg"])
    ux, uy = math.cos(ang), math.sin(ang)          # 右下向きの単位ベクトル
    tip = (tx - ux * (a["target_radius"] + a["gap"]), ty - uy * (a["target_radius"] + a["gap"]))
    tail = (tip[0] - ux * a["length"], tip[1] - uy * a["length"])
    return tail, tip, (ux, uy)


def make_arrow(cfg) -> Layer:
    a = cfg["telops"]["cta"]["arrow"]
    fade_in = cfg["telops"]["cta"]["fade_in"]
    tail, tip, (ux, uy) = arrow_geometry(cfg)
    m = 40  # 余白
    x0 = min(tail[0], tip[0]) - a["head"] - m
    y0 = min(tail[1], tip[1]) - a["head"] - m
    W = int(abs(tip[0] - tail[0]) + 2 * (a["head"] + m))
    H = int(abs(tip[1] - tail[1]) + 2 * (a["head"] + m))
    im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))

    def P(p):
        return ((p[0] - x0) * SS, (p[1] - y0) * SS)

    def draw(dr, col, off=(0, 0)):
        o = lambda p: (P(p)[0] + off[0] * SS, P(p)[1] + off[1] * SS)
        hl = a["head"]
        base = (tip[0] - ux * hl * 0.9, tip[1] - uy * hl * 0.9)
        dr.line([o(tail), o(base)], fill=col, width=a["thickness"] * SS)
        px, py = -uy, ux
        left = (tip[0] - ux * hl + px * hl * 0.62, tip[1] - uy * hl + py * hl * 0.62)
        right = (tip[0] - ux * hl - px * hl * 0.62, tip[1] - uy * hl - py * hl * 0.62)
        dr.polygon([o(tip), o(left), o(right)], fill=col)
        r = a["thickness"] * SS / 2
        tx_, ty_ = o(tail)
        dr.ellipse((tx_ - r, ty_ - r, tx_ + r, ty_ + r), fill=col)

    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw(ImageDraw.Draw(sh), (0, 0, 0, int(255 * a["shadow_opacity"])), off=(3, 3))
    sh = sh.filter(ImageFilter.GaussianBlur(4 * SS))
    im = Image.alpha_composite(im, sh)
    draw(ImageDraw.Draw(im), tuple(a["color"]) + (255,))
    im = im.resize((W, H), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32) / 255.0
    amp, period = a["nudge"]["amplitude"], a["nudge"]["period"]

    def anim(t, dur):
        al = _ease(t / fade_in) if fade_in else 1.0
        # 先端方向へ「ツン」と押し出す動き(ゆっくり戻る)
        ph = (t % period) / period
        push = amp * (math.sin(math.pi * min(1.0, ph / 0.35)) if ph < 0.35 else 0.0)
        return al, ux * push, uy * push
    return Layer(arr, x0, y0, anim)


def build_telop(kind: str, cfg, fonts, props: dict, copy: dict, room: str = "") -> list[Layer]:
    if kind == "hook":
        return make_hook(props["hook"], cfg, fonts)
    if kind == "catch":
        return make_catch(props["catch"], cfg, fonts)
    if kind == "start":
        return make_start(copy["start"]["text"], cfg, fonts)
    if kind == "room":
        r = (props.get("rooms") or {}).get(room) or copy["rooms"].get(room)
        if not r:
            return []
        return make_room(r["title"], r.get("sub", ""), cfg, fonts)
    if kind == "cta":
        return make_cta(props.get("cta") or copy["cta"]["text"], cfg, fonts)
    return []
