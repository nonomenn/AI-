"""物件フォルダ指定での一気通貫(AIなし、ファイル名で部屋判定)。書き出しまで行うので少し時間がかかる。"""
import json
import os
import subprocess

import cv2
import numpy as np

from autoedit.cli import main
from autoedit.media import probe
from conftest import make_clip

ROOMS = ["exterior", "entrance_hall", "genkan", "living_01", "living_02", "kitchen", "bedroom", "bath", "toilet",
         "balcony"]


def test_project_mode_end_to_end(tmp_path):
    root = tmp_path / "物件動画"
    (root / "共通" / "BGM").mkdir(parents=True)
    cv2.imencode(".png", np.full((1920, 1080, 3), 230, np.uint8))[1].tofile(str(root / "共通" / "広告.png"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    str(root / "共通" / "BGM" / "song.m4a")], check=True)  # 動画より短い → ループする
    pj = root / "阿波座テスト"
    (pj / "素材").mkdir(parents=True)
    for i, r in enumerate(ROOMS):
        make_clip(str(pj / "素材" / f"{i:02d}_{r}.mp4"), seconds=4.5, speed_px=50 + 5 * i)
    (pj / "property.yaml").write_text('hook: "誰もが憧れる、この空間"\ncatch: "《阿波座駅》3分の\\nデザイナーズマンション"\n',
                                      encoding="utf-8")
    main([str(pj), "--no-ai"])

    out = pj / "出力" / "阿波座テスト.mp4"
    plan = json.load(open(pj / "出力" / "阿波座テスト_plan.json", encoding="utf-8"))
    p = probe(str(out))
    assert (p.width, p.height) == (1080, 1920) and round(p.fps) == 30
    assert abs(p.duration - plan["total"]) < 0.15
    assert os.path.basename(plan["bgm"]) == "song.m4a" and os.path.basename(plan["ad"]) == "広告.png"
    secs = [x["section"] for x in plan["plan"]]
    assert secs[0] == "hook" and "ad" in secs and secs[-1] == "cta"
    # 60fps素材は0.8倍。カメラが速いカットほどさらにスロー(下限0.5倍)
    assert all(0.5 <= x["speed"] <= 0.8 for x in plan["plan"] if x["section"] != "ad")
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert abs(float(a) - plan["total"]) < 0.2  # BGMがループして最後まで鳴る
    # 完成フォルダに、物件ごとに 動画・キャプション がまとまる(番号の指定が無いので L001)
    done = root / "完成" / "No.L001_阿波座テスト"
    assert (done / "No.L001_阿波座テスト.mp4").is_file()
    cap = (done / "No.L001_阿波座テスト_キャプション.txt").read_text(encoding="utf-8")
    assert "No.L001" in cap and "【L001】" in cap
