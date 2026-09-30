"""Claude API まわり(実APIは呼ばず、応答を差し替えて検証)。"""
import json
import os

import cv2
import numpy as np
import yaml

from autoedit import intake, vision
from autoedit.analyze import Segment
from autoedit.project import open_project
from conftest import make_clip

FP = {"layout": "1LDK", "rooms": [
    {"name": "LDK 12.5帖", "type": "living", "size_jo": 12.5}, {"name": "洋室 6帖", "type": "western_room", "size_jo": 6},
    {"name": "浴室", "type": "bathroom", "size_jo": 0}, {"name": "洗面", "type": "washroom", "size_jo": 0},
    {"name": "トイレ", "type": "toilet", "size_jo": 0}, {"name": "バルコニー", "type": "balcony", "size_jo": 0}]}


def test_allowed_rooms_by_floorplan(tpl):
    types = list(tpl["room_types"])
    allowed = vision.allowed_rooms(types, FP)
    assert "japanese_room" not in allowed           # 和室は無い
    assert {"living", "dining", "kitchen"} <= set(allowed)  # LDK
    assert {"bedroom", "western_room"} <= set(allowed)
    assert "exterior" in allowed and "genkan" in allowed
    assert vision.allowed_rooms(types, None) == types
    assert vision._coerce_room("japanese_room", allowed) == "other"


def test_classify_with_fake_client(tmp_path, tpl, fake_client):
    clip = make_clip(str(tmp_path / "c.mp4"), seconds=2)
    segs = [Segment(clip=clip, start=0.2, end=1.8, fps=60, width=540, height=960, id=f"c#{i}") for i in range(3)]

    def respond(content):
        n_img = sum(1 for b in content if b["type"] == "image")
        assert n_img == 9  # 3カット × 3コマ
        return {"cuts": [{"id": "c#0", "room": "living", "beauty": 8.5, "is_transit": False, "note": "明るい"},
                         {"id": "c#1", "room": "japanese_room", "beauty": 12, "is_transit": True, "note": ""}]}

    fc = fake_client(respond)
    vision.classify_segments(segs, list(tpl["room_types"]), FP, client=fc, log=lambda *_: None)
    assert segs[0].room == "living" and segs[0].beauty == 8.5
    assert segs[1].room == "other" and segs[1].beauty == 10 and segs[1].is_transit
    kw = fc.calls[0]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    enum = kw["output_config"]["format"]["schema"]["properties"]["cuts"]["items"]["properties"]["room"]["enum"]
    assert "japanese_room" not in enum


def test_classify_survives_api_failure(tmp_path, tpl, fake_client):
    clip = make_clip(str(tmp_path / "kitchen_01.mp4"), seconds=2)
    segs = [Segment(clip=clip, start=0.2, end=1.8, fps=60, width=540, height=960, id="k#0")]
    fc = fake_client(lambda c: {}, stop_reason="refusal")
    vision.classify_segments(segs, list(tpl["room_types"]), None, client=fc, log=lambda *_: None)
    assert segs[0].room == "kitchen"  # ファイル名で判定に切り替わる


def test_normalize_catch_and_banned():
    assert intake.normalize_catch("阿波座駅3分の\\nデザイナーズマンション", "阿波座駅") == "《阿波座駅》3分の\nデザイナーズマンション"
    assert intake.normalize_catch("《《阿波座駅》3分の\nデザイナーズ", "") == "阿波座駅3分の\nデザイナーズ"
    one = intake.normalize_catch("本町駅徒歩5分のタワーマンション", "本町駅")
    assert one.count("\n") == 1 and "《本町駅》" in one
    assert intake.banned_terms("最高の眺望") == ["最高"]


def _facts():
    return {"property_name": "テストレジデンス阿波座", "building_type": "デザイナーズマンション", "station": "阿波座駅",
            "line": "大阪メトロ中央線", "walk_minutes": 3, "layout": "1LDK", "area_m2": 45.2,
            "features": ["天井高2.7m", "アイランドキッチン"],
            "floorplan": dict(found=True, source="募集図面.pdf p1", **FP),
            "hook_candidates": ["最高の眺望を手に入れる", "誰もが憧れる、この空間", "光があふれる上質な住まい"],
            "catch_candidates": ["阿波座駅3分の\nデザイナーズマンション", "《阿波座駅》徒歩3分\n天井高2.7mの1LDK"]}


def test_choose_copy():
    hook, catch, others, notes = intake.choose_copy(_facts())
    assert hook == "誰もが憧れる、この空間"   # 「最高」を含む案は除外
    assert catch == "《阿波座駅》3分の\nデザイナーズマンション"
    assert any("最高" in n for n in notes)
    assert any("天井高" in o for o in others)


def _make_project(base):
    root = base / "物件動画"
    (root / "共通" / "BGM").mkdir(parents=True)
    (root / "共通" / "フォント").mkdir()
    cv2.imencode(".png", np.full((1920, 1080, 3), 200, np.uint8))[1].tofile(str(root / "共通" / "広告.png"))
    (root / "共通" / "BGM" / "b_song.mp3").write_bytes(b"")
    (root / "共通" / "BGM" / "a_song.mp3").write_bytes(b"")
    pj = root / "阿波座テスト"
    (pj / "素材").mkdir(parents=True)
    cv2.imencode(".png", np.full((800, 600, 3), 255, np.uint8))[1].tofile(str(pj / "間取り図.png"))
    (pj / "募集図面.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (pj / "メモ.txt").write_text("x")
    return pj


def test_project_layout(tmp_path):
    pj = open_project(str(_make_project(tmp_path)))
    assert pj.name == "阿波座テスト"
    assert [os.path.basename(d) for d in pj.docs] == ["募集図面.pdf", "間取り図.png"]
    assert os.path.basename(pj.ad) == "広告.png"
    assert os.path.basename(pj.pick_bgm(None)) == "a_song.mp3"
    assert os.path.basename(pj.pick_bgm("b_song")) == "b_song.mp3"
    assert pj.font_dir.endswith("フォント")
    assert pj.out_video.endswith(os.path.join("阿波座テスト", "出力", "阿波座テスト.mp4"))


def test_run_intake_with_fake_client(tmp_path, fake_client):
    pj = open_project(str(_make_project(tmp_path)))

    def respond(content):
        types = [b["type"] for b in content]
        assert "document" in types and "image" in types
        return _facts()

    assert intake.run_intake(pj, use_ai=True, client=fake_client(respond), log=lambda *_: None)
    props = yaml.safe_load(open(pj.property_path, encoding="utf-8"))
    assert props["hook"] == "誰もが憧れる、この空間"
    assert props["catch"] == "《阿波座駅》3分の\nデザイナーズマンション"
    assert props["info"]["walk_minutes"] == 3
    fp = json.load(open(pj.floorplan_path, encoding="utf-8"))
    assert fp["layout"] == "1LDK" and len(fp["rooms"]) == 6
    # 2回目は作り直さない
    assert intake.run_intake(pj, use_ai=True, client=fake_client(lambda c: 1 / 0), log=lambda *_: None)


def test_run_intake_without_ai_writes_template(tmp_path):
    pj = open_project(str(_make_project(tmp_path)))
    assert intake.run_intake(pj, use_ai=False, log=lambda *_: None) is False
    props = yaml.safe_load(open(pj.property_path, encoding="utf-8"))
    assert props["hook"] and "○○駅" in props["catch"]
