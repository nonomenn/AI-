import numpy as np
import pytest
from PIL import Image

from autoedit.fonts import resolve_fonts
from autoedit.post import build_caption, check_post, next_number, normalize_number, record_number
from autoedit.thumbnail import parse_gold, render_thumbnail


def test_number_format():
    assert normalize_number("L36") == "L036"
    assert normalize_number("No.L032") == "L032"
    assert normalize_number(7) == "L007"
    with pytest.raises(ValueError):
        normalize_number("X12")


def test_number_counter(tmp_path):
    c = str(tmp_path / "物件番号.txt")
    assert next_number(c) == "L001"
    record_number(c, "L035")
    assert next_number(c) == "L036"
    record_number(c, "L010")  # 小さい番号(過去分の作り直し)では戻らない
    assert next_number(c) == "L036"


def test_caption_rules():
    cap = build_caption("L036", "【豊中・千里｜新築4LDK】", "本文です。\n#賃貸 #大阪\n2行目。")
    lines = cap.splitlines()
    assert lines[0] == "No.L036" and lines[2] == "【豊中・千里｜新築4LDK】"
    assert "#" not in cap and cap.rstrip().endswith("【L036】と送ってください。")
    thumb = {"title": "《新築148㎡》の4LDK。", "sub": "x", "bar": ["a", "b", "c"]}
    assert check_post("L036", {"post_title": "t"}, cap, thumb, "アルモニー千里") == []


def test_check_post_catches_problems():
    cap = build_caption("L036", "見出し", "賃料275,000円のお部屋。")
    thumb = {"title": "アルモニー千里の新築", "sub": "", "bar": ["a", "b"]}
    probs = check_post("L037", {"post_title": ""}, cap, thumb, "アルモニー千里")
    joined = " ".join(probs)
    for w in ("1行目", "CTA", "家賃", "物件名", "3項目"):
        assert w in joined


def test_parse_gold():
    assert parse_gold("《A》b《C》") == [("A", True), ("b", False), ("C", True)]


def test_render_thumbnail(tmp_path, cfg):
    fonts = resolve_fonts(cfg["fonts"], log=lambda *_: None)
    photo = np.full((1600, 1200, 3), 120, np.uint8)
    out = render_thumbnail(cfg, fonts, "《新築148㎡》×《ガレージ付き》の4LDK。", "大型犬とも暮らせるテラスハウス。",
                           ["大型犬も飼育可", "17帖のLDK", "SOHO相談可"], photo, "No.L036", str(tmp_path / "t.jpg"))
    im = Image.open(out)
    assert im.size == (1149, 1369)  # 比率は固定
    a = np.asarray(im).astype(int)
    assert a[5, 5].sum() < 30          # 黒背景
    assert a[790, 574].sum() > 600    # 中央の再生ボタン(白)
