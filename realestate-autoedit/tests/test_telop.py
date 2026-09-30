import math

from autoedit.fonts import resolve_fonts
from autoedit.telop import _parse_emphasis, arrow_geometry, build_telop


def test_arrow_points_at_icon(cfg):
    a = cfg["telops"]["cta"]["arrow"]
    tail, tip, (ux, uy) = arrow_geometry(cfg)
    tx, ty = a["target"]
    assert math.isclose(math.hypot(tx - tip[0], ty - tip[1]), a["target_radius"] + a["gap"], abs_tol=1e-6)
    assert math.isclose(math.degrees(math.atan2(tip[1] - tail[1], tip[0] - tail[0])), a["angle_deg"], abs_tol=1e-6)
    # 先端から伸ばすとアイコン中心を通る
    assert math.isclose((tx - tip[0]) * uy - (ty - tip[1]) * ux, 0, abs_tol=1e-6)


def test_parse_emphasis():
    lines, dots = _parse_emphasis("《阿波座駅》3分の\nデザイナーズマンション")
    assert lines == ["阿波座駅3分の", "デザイナーズマンション"]
    assert dots == [[0, 1, 2, 3], []]


def test_telops_render(cfg):
    fonts = resolve_fonts(cfg["fonts"], log=lambda *_: None)
    c = dict(cfg, fonts=fonts)
    props = {"hook": "誰もが憧れる、この空間", "catch": "《阿波座駅》3分の\nデザイナーズマンション", "cta": "気になった方は詳細とコメント"}
    copy = {"rooms": {"living": {"title": "Living", "sub": "暮らしの中心"}}, "cta": {"text": "x"}, "start": {"text": "ルームツアー START"}}
    W = cfg["canvas"]["width"]
    for kind in ("hook", "catch", "start", "room", "cta"):
        layers = build_telop(kind, c, fonts, props, copy, room="living")
        assert layers, kind
        for L in layers:
            assert L.img.shape[2] == 4 and L.img[..., 3].max() > 0.9
            if kind in ("hook", "catch", "room"):
                assert 0 <= L.x and L.x + L.img.shape[1] <= W  # 画面からはみ出さない
    assert build_telop("room", c, fonts, props, copy, room="unknown_room") == []
