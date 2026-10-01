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
        im = im.resize((max(1, round(im.width / SS)), max(1, round(im.height / SS))), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32) / 255.0
    return Layer(arr, cx - im.width / 2, cy - im.height / 2, anim)


def _skew(im: Image.Image, k: float) -> Image.Image:
    if not k:
        return im
    w, h = im.size
    extra = int(abs(k) * h) + 2
    return im.transform((w + extra, h), Image.AFFINE, (1, k, -k * h, 0, 1, 0), resample=Image.BICUBIC)


def _shadowed(text_img: Image.Image, shadow) -> Image.Image:
    """テキスト(RGBA)に影を付けて返す。shadow は1つ(dict)でも、重ねがけのリストでもよい
    (例: くっきりしたドロップシャドウ + 広くやわらかい影で、明るい背景でも読めるようにする)。"""
    if not shadow:
        return text_img
    shadows = shadow if isinstance(shadow, list) else [shadow]
    pad = max(int(abs(sd["offset"][0] * SS) + abs(sd["offset"][1] * SS) + sd.get("blur", 0) * SS * 3 + 4)
              for sd in shadows)
    w, h = text_img.size
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    a = text_img.split()[3]
    for sd in shadows:  # 広い影から先に描く
        ox, oy = [int(v * SS) for v in sd["offset"]]
        blur = sd.get("blur", 0) * SS
        grow = int(sd.get("spread", 0) * SS)
        aa = a.filter(ImageFilter.MaxFilter(grow * 2 + 1)) if grow else a
        sh = Image.new("RGBA", text_img.size, tuple(sd["color"]) + (0,))
        sh.putalpha(aa.point(lambda v, o=sd.get("opacity", 0.8): int(v * o)))
        canvas = Image.new("RGBA", out.size, (0, 0, 0, 0))
        if sd.get("extrude"):  # 押し出し影: 1px ずつずらして重ね、立体的なくっきりした影にする
            steps = max(abs(ox), abs(oy), 1)
            for k in range(1, steps + 1):
                canvas.paste(sh, (pad + round(ox * k / steps), pad + round(oy * k / steps)), sh)
        else:
            canvas.paste(sh, (pad + ox, pad + oy), sh)
        if blur:
            canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
        out = Image.alpha_composite(out, canvas)
    out.alpha_composite(text_img, (pad, pad))
    return out


def _text_lines(lines, font, color, spacing=1.2, letter_spacing=0, dots: list[list[int]] | None = None,
                dot_cfg: dict | None = None, parts: str = "all", crop_box=None, features=None) -> Image.Image:
    """複数行のテキストを中央揃えで描画。spacing=行送り(文字サイズ比)。dots=各行の傍点を付ける文字インデックス。"""
    def adv(c):  # features=["palt"] でかなや句読点を詰める(今の動画のテロップと同じ詰め方)
        return font.getlength(c, features=features) if features else font.getlength(c)

    def line_w(s):
        return sum(adv(c) for c in s) + letter_spacing * SS * (len(s) - 1)

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
            if parts in ("all", "text"):
                d.text((x, y), c, font=font, fill=tuple(color) + (255,), features=features)
            x += adv(c) + letter_spacing * SS
        if dots and li < len(dots) and parts in ("all", "dots"):
            for ci in dots[li]:
                cx = xs[ci] + adv(s[ci]) / 2
                cy = y + top - dot_cfg["gap_above"] * SS - r
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(color) + (255,))
        y += lh
    if crop_box is False:      # 切り抜かない(位置合わせ用)
        return im
    if crop_box is not None:
        return im.crop(crop_box)
    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im


def _x_scale(im: Image.Image, k: float) -> Image.Image:
    """横方向だけ縮める(長体)。"""
    if not k or abs(k - 1.0) < 1e-3:
        return im
    return im.resize((max(1, round(im.width * k)), im.height), Image.LANCZOS)


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
    feats = ["palt"] if c.get("palt") else None
    xs = c.get("x_scale", 1.0)
    font = _font(fonts[c["font"]], size * SS)
    while font.getlength(text, features=feats) * xs > c["max_width"] * SS and size > 40:
        size -= 2
        font = _font(fonts[c["font"]], size * SS)
    im = _x_scale(_text_lines([text], font, c["color"], features=feats), xs)
    im = _shadowed(_skew(im, c["italic_skew"]), c["shadow"])
    return [_to_layer(im, cfg["canvas"]["width"] / 2, c["center_y"], fade_anim(c["fade_in"], c["fade_out"]))]


def make_catch(text, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["catch"]
    lines, dots = _parse_emphasis(text)
    size = c["size"]
    font = _font(fonts[c["font"]], size * SS)
    feats = ["palt"] if c.get("palt") else None
    xs = c.get("x_scale", 1.0)
    while max(font.getlength(s, features=feats) for s in lines) * xs > c["max_width"] * SS and size > 40:
        size -= 2
        font = _font(fonts[c["font"]], size * SS)
    dc = c["emphasis_dot"]
    full = _text_lines(lines, font, c["color"], c["line_spacing"], dots=dots, dot_cfg=dc, crop_box=False,
                       features=feats)
    box = full.getbbox()

    def part(which):
        im = _text_lines(lines, font, c["color"], c["line_spacing"], dots=dots, dot_cfg=dc, parts=which, crop_box=box,
                         features=feats)
        return _shadowed(_skew(_x_scale(im, xs), c["italic_skew"]), c["shadow"])

    W = cfg["canvas"]["width"]
    base = fade_anim(c["fade_in"], c["fade_out"])
    layers = [_to_layer(part("text"), W / 2, c["center_y"], base)]
    if any(dots):
        bl = dc.get("blink")

        def dot_anim(t, dur):
            a, dx, dy = base(t, dur)
            if bl:  # 傍点だけ点滅(ふわっと明滅。完全には消さない)
                ph = (t % bl["period"]) / bl["period"]
                a *= bl["min_alpha"] + (1 - bl["min_alpha"]) * (0.5 + 0.5 * math.cos(2 * math.pi * ph))
            return a, dx, dy
        layers.append(_to_layer(part("dots"), W / 2, c["center_y"], dot_anim))
    return layers


def make_start(text, cfg, fonts) -> list[Layer]:
    """「ルームツアー START」: 両側から中央へ集まって現れ、最後は文字が左右に分かれて消える。"""
    c = cfg["telops"]["start"]
    font = _font(fonts[c["font"]], c["size"] * SS)
    ls = c["letter_spacing"] * SS
    widths = [font.getlength(ch) for ch in text]
    total = sum(widths) + ls * (len(text) - 1)
    W = cfg["canvas"]["width"]
    layers = []
    x = -total / 2
    for ch, w in zip(text, widths):
        cx = (x + w / 2) / SS          # 文字の中心(キャンバス中央からの距離)
        x += w + ls
        if not ch.strip():
            continue
        im = _text_lines([ch], font, c["color"])
        im = _shadowed(_skew(im, c["italic_skew"]), c["shadow"])
        side = cx / (total / SS / 2)   # -1(左端) 〜 +1(右端)

        def anim(t, dur, side=side):
            a, _, _ = fade_anim(c["fade_in"], c["fade_out"])(t, dur)
            e_in = _ease(t / c["fade_in"]) if c["fade_in"] else 1.0
            e_out = _ease((t - (dur - c["fade_out"])) / c["fade_out"]) if c["fade_out"] else 0.0
            dx = side * (c["enter_spread"] * (1 - e_in) + c["exit_spread"] * e_out)
            return a, dx, 0.0
        layers.append(_to_layer(im, W / 2 + cx, c["center_y"], anim))
    return layers


def make_room(title, sub, cfg, fonts) -> list[Layer]:
    c = cfg["telops"]["room"]
    tf = _font(fonts[c["title_font"]], c["title_size"] * SS)
    sf = _font(fonts[c["sub_font"]], c["sub_size"] * SS)
    t_im = _text_lines([title], tf, c["color"])
    s_im = _text_lines([sub], sf, c["color"], letter_spacing=c.get("sub_letter_spacing", 0)) if sub else None
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
    t_im = _x_scale(_text_lines([text], font, c["color"], letter_spacing=c.get("letter_spacing", 0),
                                features=["palt"] if c.get("palt") else None), c.get("x_scale", 1.0))
    if c.get("text_shadow"):
        t_im = _shadowed(t_im, c["text_shadow"])
    if c.get("check_icon"):
        ic = _check_icon(int(c["size"] * c.get("check_scale", 0.82) * SS), c["color"])
        gap = int(c.get("check_gap", 8) * SS)
        comb = Image.new("RGBA", (t_im.width + ic.width + gap, max(t_im.height, ic.height)), (0, 0, 0, 0))
        comb.alpha_composite(t_im, (0, (comb.height - t_im.height) // 2))
        comb.alpha_composite(ic, (t_im.width + gap, (comb.height - ic.height) // 2))
        t_im = comb
    t_im = _skew(t_im, c["italic_skew"])
    b = c["box"]
    px, py, bw = b["pad_x"] * SS, b["pad_y"] * SS, b["border"] * SS
    box = Image.new("RGBA", (t_im.width + 2 * px, t_im.height + 2 * py), (0, 0, 0, 0))
    d = ImageDraw.Draw(box)
    d.rectangle((0, 0, box.width - 1, box.height - 1), fill=tuple(b["fill"]) + (int(255 * b["fill_opacity"]),),
                outline=tuple(b["border_color"]) + (255,), width=bw)
    box.alpha_composite(t_im, (px, py))
    rv = c.get("reveal")
    if rv:  # 横線から上下に開いて現れる(今の動画と同じ)
        def box_anim(t, dur):
            p = _ease(t / rv["duration"]) if rv["duration"] else 1.0
            return (1.0 if t > 0 else 0.0), 0.0, 0.0, rv["start"] + (1 - rv["start"]) * p
    else:
        box_anim = fade_anim(c["fade_in"], 0.0)
    layers = [_to_layer(box, c["center_x"], c["center_y"], box_anim)]
    layers.append(make_arrow(cfg))
    return layers


def arrow_geometry(cfg):
    """矢印の始点・先端を計算。先端はアカウントアイコン中心へ向かい、縁の手前 gap px で止まる。"""
    a = cfg["telops"]["cta"]["arrow"]
    tx, ty = a["target"]
    ang = math.radians(a["angle_deg"])
    ux, uy = math.cos(ang), math.sin(ang)
    tip = (tx - ux * (a["target_radius"] + a["gap"]), ty - uy * (a["target_radius"] + a["gap"]))
    tail = (tip[0] - ux * a["length"], tip[1] - uy * a["length"])
    return tail, tip, (ux, uy)


def make_arrow(cfg) -> Layer:
    """細く尾が消えていく軸 + 切れ込みのある矢じり。白+重ねがけの影。先端方向へ「ツン」と動く。"""
    a = cfg["telops"]["cta"]["arrow"]
    fade_in = cfg["telops"]["cta"]["fade_in"]
    tail, tip, (ux, uy) = arrow_geometry(cfg)
    px_, py_ = -uy, ux                      # 軸に直交する向き
    hl, hw = a["head"], a["head_width"]
    m = 60
    xs = [tail[0], tip[0]]
    ys = [tail[1], tip[1]]
    x0, y0 = min(xs) - hl - m, min(ys) - hl - m
    W = int(max(xs) - min(xs) + 2 * (hl + m))
    H = int(max(ys) - min(ys) + 2 * (hl + m))

    def P(p):
        return ((p[0] - x0) * SS, (p[1] - y0) * SS)

    def shape():
        """白い矢印の形(RGBA)。軸は尾に向かって細く、透明になる。"""
        base = (tip[0] - ux * hl * 0.72, tip[1] - uy * hl * 0.72)
        w0, w1 = a["tail_width"] / 2, a["thickness"] / 2
        shaft = [(tail[0] + px_ * w0, tail[1] + py_ * w0), (base[0] + px_ * w1, base[1] + py_ * w1),
                 (base[0] - px_ * w1, base[1] - py_ * w1), (tail[0] - px_ * w0, tail[1] - py_ * w0)]
        back = (tip[0] - ux * hl, tip[1] - uy * hl)
        notch = (tip[0] - ux * hl * a["notch"], tip[1] - uy * hl * a["notch"])
        head = [tip, (back[0] + px_ * hw / 2, back[1] + py_ * hw / 2), notch,
                (back[0] - px_ * hw / 2, back[1] - py_ * hw / 2)]
        m_shaft = Image.new("L", (W * SS, H * SS), 0)
        ImageDraw.Draw(m_shaft).polygon([P(q) for q in shaft], fill=255)
        # 軸方向のグラデーション(尾 15% → 付け根 100%)
        yy, xx = np.mgrid[0:H * SS, 0:W * SS].astype(np.float32)
        tpos = ((xx / SS + x0 - tail[0]) * ux + (yy / SS + y0 - tail[1]) * uy) / a["length"]
        grad = 0.15 + 0.85 * np.clip(tpos, 0, 1) ** 0.7
        m = (np.asarray(m_shaft, np.float32) * grad).astype(np.uint8)
        m_img = Image.fromarray(m)
        ImageDraw.Draw(m_img).polygon([P(q) for q in head], fill=255)
        body = Image.new("RGBA", m_img.size, tuple(a["color"]) + (0,))
        body.putalpha(m_img)
        return body

    body = shape()
    alpha = body.split()[3]
    layers = []
    for sd in a["shadow"]:  # 文字と同じく、広く暗い影 + くっきりした影で明るい背景でも見えるように
        grow = int(sd.get("spread", 0) * SS)
        aa = alpha.filter(ImageFilter.MaxFilter(grow * 2 + 1)) if grow else alpha
        sh = Image.new("RGBA", body.size, tuple(sd["color"]) + (0,))
        sh.putalpha(aa.point(lambda v, o=sd["opacity"]: int(v * o)))
        canvas = Image.new("RGBA", body.size, (0, 0, 0, 0))
        canvas.paste(sh, (int(sd["offset"][0] * SS), int(sd["offset"][1] * SS)), sh)
        layers.append(canvas.filter(ImageFilter.GaussianBlur(sd.get("blur", 0) * SS)))
    im = Image.new("RGBA", body.size, (0, 0, 0, 0))
    for L_ in layers:
        im = Image.alpha_composite(im, L_)
    im = Image.alpha_composite(im, body)
    im = im.resize((W, H), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32) / 255.0
    amp, period = a["nudge"]["amplitude"], a["nudge"]["period"]

    def anim(t, dur):
        al = _ease(t / fade_in) if fade_in else 1.0
        # 先端方向へ「ツン」と押し出して、ゆっくり戻る
        ph = (t % period) / period
        push = amp * math.sin(math.pi * ph / 0.3) if ph < 0.3 else 0.0
        slide = (1 - _ease(t / 0.5)) * -40 if t < 0.5 else 0.0   # 出るときは左から少し滑り込む
        return al, ux * (push + slide), uy * (push + slide)
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
