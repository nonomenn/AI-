"""サムネイル(黒×ゴールドのテンプレート)の書き出し。

完成見本(No.L030〜L032)のレイアウトを固定し、差し替えるのは次だけ:
  タイトル(《》で囲んだ部分がゴールド) / サブタイトル / 情報バー3項目 / 物件写真 / 物件番号
数値は style.yaml の thumbnail(1149×1369 基準)。サムネに物件名は入れない(post.check_thumbnail で検査)。
"""
from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 2  # スーパーサンプリング
CIRCLED = "①②③④⑤"


def _font(path, size):
    return ImageFont.truetype(path, int(size), index=0)


def _gradient(size, stops) -> Image.Image:
    """縦グラデーション(RGB)。stops は上→下の色のリスト。"""
    w, h = size
    ys = np.linspace(0, 1, h)
    pos = np.linspace(0, 1, len(stops))
    cols = np.stack([np.interp(ys, pos, [c[i] for c in stops]) for i in range(3)], 1)
    return Image.fromarray(np.repeat(cols[:, None, :], w, 1).astype(np.uint8), "RGB")


def parse_gold(text: str) -> list[tuple[str, bool]]:
    """「《新築148㎡》×《ガレージ付き》の4LDK。」→ [(文字, ゴールドか), ...]"""
    out, gold = [], False
    for ch in text:
        if ch == "《":
            gold = True
        elif ch == "》":
            gold = False
        else:
            out.append((ch, gold))
    return out


def _is_kana_small(ch: str) -> bool:
    return bool(re.match(r"[ぁ-ゟ、。・]", ch))


def _rich_line(chars, font_path, size, gold_stops, white, digit_scale=1.0, kana_scale=1.0) -> Image.Image:
    """1行の混在テキスト(ゴールド/白、数字だけ大きく、白のかなを少し小さく)を RGBA で描く。ベースライン揃え。"""
    runs = []
    for ch, g in chars:
        s = size
        if g and ch.isdigit():
            s = size * digit_scale
        elif not g and _is_kana_small(ch):
            s = size * kana_scale
        runs.append((ch, g, _font(font_path, s * SS)))
    asc = max(f.getmetrics()[0] for _, _, f in runs)
    desc = max(f.getmetrics()[1] for _, _, f in runs)
    W = int(sum(f.getlength(c) for c, _, f in runs)) + 8 * SS
    H = asc + desc + 8 * SS
    mask_g = Image.new("L", (W, H), 0)
    mask_w = Image.new("L", (W, H), 0)
    dg, dw = ImageDraw.Draw(mask_g), ImageDraw.Draw(mask_w)
    x = 4 * SS
    for c, g, f in runs:
        (dg if g else dw).text((x, 4 * SS + asc), c, font=f, fill=255, anchor="ls")
        x += f.getlength(c)
    grad = _gradient((W, H), gold_stops).convert("RGBA")
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad.putalpha(mask_g)
    out.alpha_composite(grad)
    wl = Image.new("RGBA", (W, H), tuple(white) + (0,))
    wl.putalpha(mask_w)
    out.alpha_composite(wl)
    bbox = out.getbbox()
    return out.crop((bbox[0], 0, bbox[2], H)) if bbox else out


def _fit(render, max_w, size, min_size=24):
    im = render(size)
    while im.width > max_w * SS and size > min_size:
        size -= 2
        im = render(size)
    return im


def _shadow(im: Image.Image, radius=6, opacity=0.6) -> Image.Image:
    pad = radius * 3
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(im.split()[3].point(lambda v: int(v * opacity)))
    out.alpha_composite(sh, (pad, pad + radius // 2))
    out = out.filter(ImageFilter.GaussianBlur(radius))
    out.alpha_composite(im, (pad, pad))
    return out


def _paste_center(canvas: Image.Image, im: Image.Image, cx, cy):
    canvas.alpha_composite(im, (int(cx * SS - im.width / 2), int(cy * SS - im.height / 2)))


def _cover(photo: np.ndarray, w: int, h: int, focus_y: float = 0.5) -> Image.Image:
    ph, pw = photo.shape[:2]
    s = max(w / pw, h / ph)
    img = cv2.resize(photo, (int(round(pw * s)), int(round(ph * s))), interpolation=cv2.INTER_AREA)
    x0 = (img.shape[1] - w) // 2
    y0 = int((img.shape[0] - h) * focus_y)
    img = img[y0:y0 + h, x0:x0 + w]
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")


def render_thumbnail(cfg: dict, fonts: dict, title: str, sub: str, bar: list[str], photo: np.ndarray,
                     number: str, out_path: str, photo_focus_y: float = 0.5) -> str:
    T = cfg["thumbnail"]
    W, H = T["width"], T["height"]
    gold, white, line_gold = T["gold"], T["white"], tuple(T["line_gold"])
    f_title = fonts[T["fonts"]["title"]]
    f_text = fonts[T["fonts"]["text"]]
    cv = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 255))
    d = ImageDraw.Draw(cv)

    # 外枠
    fr = T["frame"]
    i, lw = fr["inset"] * SS, fr["width"] * SS
    d.rectangle((i, i, W * SS - 1 - i, H * SS - 1 - i), outline=line_gold + (255,), width=lw)
    # 最上部の光るライン(中央が明るく、両端へ消える)
    g = T["glow"]
    gw, gh = g["width"] * SS, max(1, g["height"] * SS)
    xs = np.linspace(-1, 1, gw)
    alpha = (np.clip(1 - np.abs(xs) ** 1.6, 0, 1) * 255).astype(np.uint8)
    glow = Image.new("RGBA", (gw, gh * 7), (0, 0, 0, 0))
    core = Image.new("RGBA", (gw, gh), (255, 214, 130, 0))
    core.putalpha(Image.fromarray(np.repeat(alpha[None, :], gh, 0)))
    glow.alpha_composite(core, (0, gh * 3))
    glow = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(gh * 1.5)), glow)
    cv.alpha_composite(glow, (int(W * SS / 2 - gw / 2), int(g["y"] * SS - glow.height / 2)))

    # タイトル
    t = T["title"]
    chars = parse_gold(title)
    im = _fit(lambda s: _rich_line(chars, f_title, s, gold, white, t["digit_scale"], t["kana_scale"]),
              t["max_width"], t["size"])
    _paste_center(cv, _shadow(im), W / 2, t["center_y"])
    # サブタイトル
    s_ = T["sub"]
    im = _fit(lambda s: _rich_line(parse_gold(sub), f_text, s, gold, white), s_["max_width"], s_["size"])
    _paste_center(cv, _shadow(im, 4, 0.5), W / 2, s_["center_y"])

    # 情報バー(3分割。区切りの位置は文字量に合わせる)
    b = T["bar"]
    x0, x1, y0, y1 = b["x0"], b["x1"], b["y0"], b["y1"]
    d.rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS), outline=line_gold + (255,), width=b["border"] * SS)
    items = [f"{CIRCLED[k]} {txt}" for k, txt in enumerate(bar[:3])]
    size = b["size"]
    fb = _font(f_text, size * SS)
    widths = [fb.getlength(s) + 44 * SS for s in items]
    while sum(widths) > (x1 - x0) * SS and size > 20:
        size -= 1
        fb = _font(f_text, size * SS)
        widths = [fb.getlength(s) + 36 * SS for s in items]
    extra = ((x1 - x0) * SS - sum(widths)) / max(1, len(items))
    cx = x0 * SS
    for k, (s, w) in enumerate(zip(items, widths)):
        w += extra
        if k:
            d.line((cx, y0 * SS, cx, y1 * SS), fill=line_gold + (255,), width=b["border"] * SS)
        d.text((cx + w / 2, (y0 + y1) / 2 * SS), s, font=fb, fill=tuple(b["color"]) + (255,), anchor="mm")
        cx += w

    # 物件写真(角丸+ゴールド枠)と再生ボタン
    p = T["photo"]
    pw, ph = (p["x1"] - p["x0"]) * SS, (p["y1"] - p["y0"]) * SS
    ph_img = _cover(photo, pw, ph, photo_focus_y)
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), p["radius"] * SS, fill=255)
    ph_img.putalpha(mask)
    cv.alpha_composite(ph_img, (p["x0"] * SS, p["y0"] * SS))
    d = ImageDraw.Draw(cv)
    d.rounded_rectangle((p["x0"] * SS, p["y0"] * SS, p["x1"] * SS, p["y1"] * SS), p["radius"] * SS,
                        outline=line_gold + (255,), width=p["border"] * SS)
    pl = T["play"]
    (px, py), r, st = pl["center"], pl["radius"] * SS, pl["stroke"] * SS
    ov = Image.new("RGBA", cv.size, (0, 0, 0, 0))
    do = ImageDraw.Draw(ov)
    do.ellipse((px * SS - r, py * SS - r, px * SS + r, py * SS + r), fill=(0, 0, 0, 40),
               outline=(255, 255, 255, 255), width=st)
    tr = r * 0.46
    cxp = px * SS + tr * 0.18
    do.polygon([(cxp - tr * 0.62, py * SS - tr), (cxp - tr * 0.62, py * SS + tr), (cxp + tr * 1.0, py * SS)],
               fill=(255, 255, 255, 255))
    sh = ov.filter(ImageFilter.GaussianBlur(6 * SS))
    cv.alpha_composite(sh)
    cv.alpha_composite(ov)

    # 物件番号(左右にゴールド線)
    n = T["number"]
    im = _rich_line(parse_gold(f"《{number}》"), f_text, n["size"], gold, white)
    _paste_center(cv, im, W / 2, n["center_y"])
    half = im.width / SS / 2
    d = ImageDraw.Draw(cv)
    for sgn in (-1, 1):
        a = W / 2 + sgn * (half + n["line_gap"])
        bnd = a + sgn * n["line_len"]
        d.line((min(a, bnd) * SS, n["center_y"] * SS, max(a, bnd) * SS, n["center_y"] * SS),
               fill=line_gold + (255,), width=n["line_width"] * SS)

    cv.resize((W, H), Image.LANCZOS).convert("RGB").save(out_path, quality=95)
    return out_path
