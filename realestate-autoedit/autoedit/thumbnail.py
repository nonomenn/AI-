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
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if mask_g.getbbox():
        out.alpha_composite(metallic_gold(mask_g, gold_stops))
    wl = Image.new("RGBA", (W, H), tuple(white) + (0,))
    wl.putalpha(mask_w)
    out.alpha_composite(wl)
    bbox = out.getbbox()
    return out.crop((bbox[0], 0, bbox[2], H)) if bbox else out


def metallic_gold(mask: Image.Image, gold: dict) -> Image.Image:
    """光沢のあるゴールド文字(RGBA)。完成見本の再現:
    文字の高さに合わせた金属的な縦グラデーション(上が明るい黄金、中に光の帯、下は琥珀色)
    + 左上から光が当たる面取り(上側の縁を明るく、下側の縁を暗く) + 細い焦げ茶の縁取り。"""
    a = np.asarray(mask, np.float32) / 255.0
    H, W = a.shape
    rows = np.where(a.max(1) > 0.1)[0]
    y0, y1 = (rows.min(), rows.max()) if len(rows) else (0, H - 1)
    t = np.clip((np.arange(H) - y0) / max(1, y1 - y0), 0, 1)
    stops = gold["stops"]
    pos = [s[0] for s in stops]
    col = np.stack([np.interp(t, pos, [s[1 + i] for s in stops]) for i in range(3)], 1)   # (H, 3)
    img = np.repeat(col[:, None, :], W, 1)
    # 面取り: ぼかした文字形の傾きから、光の当たる縁(左上向き)と影の縁を作る
    bl = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(gold["bevel"] * SS)), np.float32) / 255.0
    gy, gx = np.gradient(bl)
    light = -(gy * 0.85 + gx * 0.35)
    light /= (np.abs(light).max() + 1e-6)
    hi = np.clip(light, 0, 1)[..., None]
    lo = np.clip(-light, 0, 1)[..., None]
    img = img + (255 - img) * hi * gold["highlight"] - img * lo * gold["shade"]
    body = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    body.putalpha(mask)
    # 細い焦げ茶の縁取り(文字の輪郭をくっきりさせる)
    w = max(1, int(round(gold["outline"] * SS)))
    edge = mask.filter(ImageFilter.MaxFilter(w * 2 + 1))
    out = Image.new("RGBA", mask.size, tuple(gold["outline_color"]) + (0,))
    out.putalpha(edge)
    out.alpha_composite(body)
    return out


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
    d.rounded_rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS), b.get("radius", 0) * SS, outline=line_gold + (255,),
                        width=b["border"] * SS)
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
        # 丸数字はゴールド、本文は白に近い色(完成見本どおり)
        num, rest = s[:1], s[1:]
        fn = _font(f_text, size * b.get("number_scale", 1.0) * SS)
        tw = fn.getlength(num) + fb.getlength(rest)
        x = cx + w / 2 - tw / 2
        cy = (y0 + y1) / 2 * SS
        d.text((x, cy), num, font=fn, fill=tuple(b["number_color"]) + (255,), anchor="lm")
        d.text((x + fn.getlength(num), cy), rest, font=fb, fill=tuple(b["color"]) + (255,), anchor="lm")
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
