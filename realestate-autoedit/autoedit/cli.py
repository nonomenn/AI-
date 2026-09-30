"""コマンドライン入口。

本番(物件フォルダを指定するだけ):
  python -m autoedit 物件動画/物件名
    素材=物件名/素材/、物件資料=物件名/ 直下、広告・BGM・書体=物件動画/共通/、書き出し=物件名/出力/
    property.yaml が無ければ、物件資料から自動生成してから編集する

個別指定(デモ・検証用):
  python -m autoedit --clips 素材フォルダ --property property.yaml --out out.mp4 \
      [--floorplan 間取り.jpg|floorplan.json] [--ad 広告.png] [--bgm bgm.mp3] [--labels labels.yaml] [--override demo.yaml]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import yaml

from . import vision
from .analyze import analyze_all
from .fonts import FontNotFound, resolve_fonts
from .media import MediaError, require_ffmpeg
from .planner import build_plan
from .render import render, timeline

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_EXT = (".mp4", ".mov", ".m4v")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge(a: dict, b: dict) -> dict:
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def _resolve(path: str | None, *bases: str) -> str | None:
    """相対パスを、カレント → 指定のフォルダ(property.yaml の場所など)の順で探す。"""
    if not path or os.path.isabs(path):
        return path
    for b in ("",) + bases:
        p = os.path.join(b, path) if b else path
        if os.path.exists(p):
            return p
    return path


def _collect_clips(path: str) -> list[str]:
    if os.path.isdir(path):
        return sorted(p for p in glob.glob(os.path.join(path, "*")) if p.lower().endswith(VIDEO_EXT))
    return [path]


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m autoedit", description="不動産ルームツアー動画 自動編集")
    ap.add_argument("project", nargs="?", help="物件フォルダ(物件動画/物件名)。指定すると下の個別指定は省略できる")
    ap.add_argument("--clips", help="動画素材のフォルダ(またはファイル)")
    ap.add_argument("--property", help="物件ごとの文言 property.yaml")
    ap.add_argument("--out", help="書き出し先 .mp4")
    ap.add_argument("--floorplan", help="間取り図の画像、または floorplan.json")
    ap.add_argument("--ad", help="広告の静止画(1080x1920推奨)")
    ap.add_argument("--bgm", help="BGM音源")
    ap.add_argument("--labels", help="手動ラベル(AIを使わない/上書きしたい場合)")
    ap.add_argument("--override", help="style.yaml の一部を上書きするyaml")
    ap.add_argument("--no-ai", action="store_true", help="Claude APIを使わない")
    ap.add_argument("--regen-property", action="store_true", help="物件資料から property.yaml を作り直す")
    ap.add_argument("--plan-only", action="store_true", help="構成表だけ作って書き出さない")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        require_ffmpeg()
        return run(args)
    except (MediaError, FontNotFound, FileNotFoundError, vision.VisionError) as e:
        sys.exit(f"エラー: {e}")


def run(args):
    cfg = _load(os.path.join(HERE, "config/style.yaml"))
    if args.override:
        _merge(cfg, _load(args.override))
    tpl = _load(os.path.join(HERE, "config/template.yaml"))
    copy = _load(os.path.join(HERE, "config/copy.yaml"))
    use_ai = not args.no_ai and vision.ai_available()

    font_dir = None
    floorplan_arg = args.floorplan
    if args.project:
        from .intake import run_intake
        from .project import open_project
        pj = open_project(args.project)
        print(f"物件: {pj.name}  ({pj.root})")
        if not pj.common_dir:
            print("  ⚠ 共通フォルダ(物件動画/共通/)が見つかりません。広告・BGMなしで作ります")
        print("[0/5] 物件資料の読み取り → property.yaml")
        if not run_intake(pj, force=args.regen_property, use_ai=use_ai):
            sys.exit("property.yaml の雛形を作りました。hook と catch を書き換えてから、もう一度実行してください")
        clips = _collect_clips(args.clips) if args.clips else pj.clips
        prop_path = args.property or pj.property_path
        out = args.out or pj.out_video
        if not floorplan_arg and os.path.exists(pj.floorplan_path):
            floorplan_arg = pj.floorplan_path
        font_dir = pj.font_dir
        props = _load(prop_path)
        ad = args.ad or _resolve(props.get("ad_image"), pj.root) or pj.ad
        bgm = args.bgm or pj.pick_bgm(props.get("bgm"))
    else:
        if not (args.clips and args.property and args.out):
            sys.exit("物件フォルダを指定するか、--clips --property --out を指定してください")
        clips = _collect_clips(args.clips)
        prop_path, out = args.property, args.out
        props = _load(prop_path)
        pdir = os.path.dirname(os.path.abspath(prop_path))
        ad = args.ad or _resolve(props.get("ad_image"), pdir)
        bgm = args.bgm or _resolve(props.get("bgm"), pdir)

    for k in ("hook", "catch"):
        if not props.get(k):
            sys.exit(f"property.yaml に {k} がありません: {prop_path}")
        if "○○" in str(props[k]):
            sys.exit(f"property.yaml の {k} が雛形のままです(「○○」を書き換えてください): {prop_path}")
    if not clips:
        sys.exit("動画素材が見つかりません")
    for p, what in ((ad, "広告画像"), (bgm, "BGM")):
        if p and not os.path.isfile(p):
            sys.exit(f"{what}が見つかりません: {p}")
    fonts = resolve_fonts(cfg["fonts"], font_dir)
    cfg["fonts"] = fonts

    out_dir = os.path.dirname(os.path.abspath(out))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(out))[0]

    print(f"[1/5] 素材解析(移動・手ブレ・ピンボケを除外) {len(clips)}本")
    segs, _ = analyze_all(clips, cfg)

    floorplan = None
    print("[2/5] 間取り図")
    if floorplan_arg and floorplan_arg.lower().endswith(".json"):
        with open(floorplan_arg, encoding="utf-8") as f:
            floorplan = json.load(f)
    elif floorplan_arg and use_ai:
        floorplan = vision.read_floorplan(floorplan_arg)
    if floorplan and floorplan.get("rooms"):
        print(f"  {floorplan.get('layout', '')}: " + ", ".join(r["name"] for r in floorplan["rooms"]))
    else:
        floorplan = None
        print("  なし(部屋の除外なしで判定)")

    print("[3/5] 各カットの部屋判定・映え度")
    room_types = list(tpl["room_types"].keys())
    if use_ai:
        vision.classify_segments(segs, room_types, floorplan)
    else:
        vision.label_from_filename(segs)
        print("  AIを使わないため、ファイル名/手動ラベルで判定")
    if args.labels:
        vision.apply_manual_labels(segs, args.labels)
    for s in segs:
        print(f"  {s.id:<20} {s.start:5.1f}-{s.end:5.1f}s  {s.room:<13} 映え{s.beauty:>4.1f}"
              f"  安定{s.score:.2f}{'  (移動中→不使用)' if s.is_transit else ''}  {s.note}")

    print("[4/5] 構成の組み立て")
    plan = build_plan(segs, cfg, tpl, ad)
    starts, total = timeline(plan)
    for st, p in zip(starts, plan):
        tr = p.transition_in
        trs = f"  ←{tr['type']} {tr['duration']}s" if tr else ""
        print(f"  {st:5.1f}s {p.describe()}{trs}")
    print(f"  合計 {total:.1f}秒")
    with open(os.path.join(out_dir, f"{stem}_plan.json"), "w", encoding="utf-8") as f:
        json.dump({"total": total, "floorplan": floorplan, "bgm": bgm, "ad": ad,
                   "segments": [s.to_dict() for s in segs],
                   "plan": [{"start": st, "section": p.section, "clip": p.seg.clip if p.seg else p.image,
                             "src_start": p.src_start, "duration": p.duration, "speed": p.speed,
                             "room": p.room, "telop": p.telop, "transition_in": p.transition_in}
                            for st, p in zip(starts, plan)]}, f, ensure_ascii=False, indent=2)
    if args.plan_only:
        return

    print("[5/5] 書き出し")
    render(plan, cfg, fonts, props, copy, out, bgm=bgm)


if __name__ == "__main__":
    main()
