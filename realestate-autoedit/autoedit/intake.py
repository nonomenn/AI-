"""物件資料(PDF・画像、間取り図入り)を読み、property.yaml を自動で作る。

  python -m autoedit.intake 物件動画/物件名            # property.yaml が無ければ作る
  python -m autoedit.intake 物件動画/物件名 --force    # 作り直す

物件フォルダ直下の資料をまとめて Claude に渡し、次を1回で読み取る:
  - 物件情報(最寄駅・徒歩分数・間取り・特徴 など) → 物件情報.json
  - 間取り図(部屋の一覧と帖数)                  → floorplan.json(カット判定と部屋テロップに使う)
  - hook(見所コピー)とキャッチ(《》で傍点)の案   → property.yaml(1案目を採用し、他の案はコメントで残す)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import vision
from .project import Project, open_project

MAX_REQUEST_MB = 28  # APIの1リクエスト上限(32MB)に余裕を持たせる

# 不動産の表示に関する公正競争規約で、根拠なく使えない用語(代表的なもの)
BANNED_TERMS = ["完全", "完璧", "絶対", "万全", "日本一", "業界一", "No.1", "ナンバーワン", "抜群", "特選", "厳選",
                "最高", "最高級", "最上", "最安", "格安", "激安", "破格", "掘出", "掘り出し", "買得", "超"]

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "property_name": {"type": "string"},
        "building_type": {"type": "string"},
        "station": {"type": "string"},
        "line": {"type": "string"},
        "walk_minutes": {"type": "integer"},
        "layout": {"type": "string"},
        "area_m2": {"type": "number"},
        "features": {"type": "array", "items": {"type": "string"}},
        "floorplan": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "source": {"type": "string"},
                "layout": {"type": "string"},
                "rooms": vision.FLOORPLAN_SCHEMA["properties"]["rooms"],
            },
            "required": ["found", "source", "layout", "rooms"], "additionalProperties": False,
        },
        "hook_candidates": {"type": "array", "items": {"type": "string"}},
        "catch_candidates": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["property_name", "building_type", "station", "line", "walk_minutes", "layout", "area_m2",
                 "features", "floorplan", "hook_candidates", "catch_candidates"],
    "additionalProperties": False,
}

INTAKE_PROMPT = """添付は1物件分の物件詳細資料(募集図面・物件概要・間取り図など)です。
TikTok用ルームツアー動画(高級賃貸・TOALU ESTATE)のために、次を読み取ってください。

1. 物件情報(資料に書かれていることだけ。推測で埋めない。無い項目は空文字 / 0 / 空配列)
 - property_name: 物件名(建物名)
 - building_type: 物件種別を短く(例: デザイナーズマンション、タワーマンション、戸建て)
 - station / line / walk_minutes: 最寄駅(「駅」を含む表記。例: 阿波座駅)・路線・徒歩分数。複数あれば一番近いもの
 - layout / area_m2: 間取りタイプ(例: 1LDK)・専有面積(㎡)
 - features: 動画の見どころになる特徴を最大6個、短く(例: 天井高2.7m、アイランドキッチン、南向きバルコニー)

2. floorplan: 間取り図の読み取り。source には間取り図が載っていたファイル名(PDFならファイル名とページ)。
{floorplan_rules}

3. hook_candidates: 冒頭2秒に出す見所コピーを3案。
 - 全角11文字以内。極太明朝で1行で出す。物件の一番の魅力を、上品で憧れを誘う言い方で
 - 例: 「誰もが憧れる、この空間」
4. catch_candidates: 物件キャッチを3案。
 - 2行(改行は \\n)。各行 全角12文字以内。1行目で立地、2行目で物件種別や一番の特徴
 - 一番刺さる語(多くは駅名)を《》で1か所だけ囲む(その文字の上に傍点が付く)
 - 例: 「《阿波座駅》3分の\\nデザイナーズマンション」
 - 資料に無い事実は書かない。徒歩分数・駅名は資料どおり

コピーの注意(不動産の表示に関する公正競争規約): 「完全」「完璧」「絶対」「日本一」「最高」「抜群」「格安」「超」など、
根拠を示せない最上級・断定表現は使わないこと。"""


def _docs_content(docs: list[str]) -> list[dict]:
    total = sum(os.path.getsize(d) for d in docs)
    if total / 1e6 > MAX_REQUEST_MB * 0.74:  # base64 で約1.35倍になる
        raise vision.VisionError(
            f"物件資料が大きすぎます(計{total / 1e6:.0f}MB)。間取り図と概要のページだけに絞ってください")
    content = []
    for d in docs:
        content.append({"type": "text", "text": f"ファイル: {os.path.basename(d)}"})
        content.extend(vision.file_blocks(d))
    return content


def read_documents(docs: list[str], model: str = vision.DEFAULT_MODEL, client=None) -> dict:
    content = _docs_content(docs)
    content.append({"type": "text", "text": INTAKE_PROMPT.replace("{floorplan_rules}", vision.FLOORPLAN_RULES)})
    return vision.ask_json(content, FACTS_SCHEMA, model, max_tokens=8000, client=client)


# ------------------------------------------------------------------ コピーの整形・検査
def banned_terms(text: str) -> list[str]:
    return [w for w in BANNED_TERMS if w in text]


def normalize_catch(text: str, station: str = "") -> str:
    """キャッチを2行・《》1か所に整える。"""
    t = text.replace("\\n", "\n").strip()
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    if len(lines) == 1:
        s = lines[0]
        # 「の」「、」の直後で切る(無ければ真ん中)
        m = re.search(r"(?<=[のでな、])", s[3:-2]) if len(s) > 6 else None
        k = (m.start() + 3) if m else len(s) // 2
        lines = [s[:k], s[k:]]
    t = "\n".join(lines[:2])
    opens, closes = t.count("《"), t.count("》")
    if opens != closes or opens > 1:
        t = t.replace("《", "").replace("》", "")
        opens = 0
    if opens == 0 and station and station in t:
        t = t.replace(station, f"《{station}》", 1)
    return t


def _visible_len(s: str) -> int:
    return len(s.replace("《", "").replace("》", ""))


def choose_copy(facts: dict) -> tuple[str, str, list[str], list[str]]:
    """候補から hook / catch を1つずつ選ぶ。戻り値: (hook, catch, ほかの案, 注意メッセージ)"""
    notes = []
    station = facts.get("station", "")

    def pick(cands, fix, max_len):
        good, ok = [], []
        for c in cands:
            c = fix(c)
            if not c or banned_terms(c):
                if c:
                    notes.append(f"規約上の注意語 {banned_terms(c)} を含むため除外: {c!r}")
                continue
            (good if all(_visible_len(ln) <= max_len for ln in c.split("\n")) else ok).append(c)
        return (good + ok), bool(good)

    hooks, fit = pick(facts.get("hook_candidates", []), lambda s: s.strip().replace("\n", ""), 11)
    if hooks and not fit:
        notes.append("hook がどの案も11文字を超えています(自動で縮小して表示されます)")
    catches, fit = pick(facts.get("catch_candidates", []), lambda s: normalize_catch(s, station), 12)
    if catches and not fit:
        notes.append("キャッチの行がどの案も12文字を超えています(自動で縮小して表示されます)")
    if not hooks:
        hooks = ["誰もが憧れる、この空間"]
        notes.append("hook の案が使えなかったため定型文にしました。property.yaml で直してください")
    if not catches:
        loc = f"《{station}》" + (f"{facts['walk_minutes']}分の" if facts.get("walk_minutes") else "の") if station else ""
        catches = [f"{loc}\n{facts.get('building_type') or 'デザイナーズマンション'}"]
        notes.append("キャッチの案が使えなかったため物件情報から作りました。property.yaml で直してください")
    return hooks[0], catches[0], hooks[1:] + [f"(キャッチ) {c}" for c in catches[1:]], notes


# ------------------------------------------------------------------ property.yaml の書き出し
def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # YAML でも有効なダブルクォート文字列


def property_yaml(hook: str, catch: str, facts: dict | None, others: list[str], notes: list[str],
                  sources: list[str]) -> str:
    out = ["# 物件ごとの文言(autoedit.intake が物件資料から自動生成。自由に書き換えてよい)"]
    if sources:
        out.append("# 読み取った資料: " + ", ".join(os.path.basename(s) for s in sources))
    for n in notes:
        out.append(f"# ⚠ {n}")
    out += [f"hook: {_q(hook)}",
            f"catch: {_q(catch)}   # 《》で囲んだ文字の上に傍点(●)。\\n で改行",
            'cta: "気になった方は詳細とコメント"']
    if others:
        out.append("# ほかの案:")
        out += [f"#   {o.replace(chr(10), ' / ')}" for o in others]
    if facts:
        out.append("")
        out.append("# 資料から読み取った物件情報(確認用。動画には直接使わない)")
        info = {k: facts.get(k) for k in ("property_name", "building_type", "station", "line", "walk_minutes",
                                           "layout", "area_m2", "features")}
        out.append("info: " + json.dumps(info, ensure_ascii=False))
    out += ["",
            "# bgm: 曲名.mp3        # 共通/BGM/ の中から選ぶ(未指定は名前順で先頭)",
            "# rooms:               # 部屋紹介の文言を物件ごとに変えたいときだけ書く(未指定は config/copy.yaml)",
            '#   living: {title: "Living", sub: "陽光が差し込む開放的な空間"}', ""]
    return "\n".join(out)


def run_intake(pj: Project, force: bool = False, use_ai: bool | None = None, log=print, client=None) -> bool:
    """property.yaml を用意する。AIで作れた/既にあれば True、雛形だけ作った(人が埋める必要がある)なら False。"""
    if os.path.exists(pj.property_path) and not force:
        log(f"  property.yaml は作成済み(作り直すときは --force): {pj.property_path}")
        return True
    use_ai = vision.ai_available() if use_ai is None else use_ai
    if not pj.docs:
        log("  ⚠ 物件資料(PDF・画像)が物件フォルダ直下にありません")
    if not use_ai or not pj.docs:
        text = property_yaml("誰もが憧れる、この空間", "《○○駅》○分の\nデザイナーズマンション", None, [],
                             ["AIを使えないため雛形です。hook と catch を物件に合わせて書き換えてください"], [])
        with open(pj.property_path, "w", encoding="utf-8") as f:
            f.write(text)
        log(f"  雛形を作りました: {pj.property_path}")
        return False

    log(f"  物件資料 {len(pj.docs)}件を読み取り中: " + ", ".join(os.path.basename(d) for d in pj.docs))
    facts = read_documents(pj.docs, client=client)
    hook, catch, others, notes = choose_copy(facts)
    with open(pj.facts_path, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=2)
    fp = facts.get("floorplan") or {}
    if fp.get("found") and fp.get("rooms"):
        with open(pj.floorplan_path, "w", encoding="utf-8") as f:
            json.dump({"layout": fp.get("layout") or facts.get("layout", ""), "rooms": fp["rooms"],
                       "source": fp.get("source", "")}, f, ensure_ascii=False, indent=2)
        log(f"  間取り図({fp.get('source', '')}): {fp.get('layout', '')} "
            + ", ".join(r["name"] for r in fp["rooms"]))
    else:
        if os.path.exists(pj.floorplan_path):
            os.remove(pj.floorplan_path)  # 作り直しのとき、前の読み取り結果を残さない
        log("  ⚠ 資料に間取り図が見つかりませんでした(部屋の除外なしで判定します)")
    with open(pj.property_path, "w", encoding="utf-8") as f:
        f.write(property_yaml(hook, catch, facts, others, notes, pj.docs))
    loc = facts.get("station", "") + (f" 徒歩{facts['walk_minutes']}分" if facts.get("walk_minutes") else "")
    log(f"  物件情報: {facts.get('property_name', '')} / {loc} / {facts.get('layout', '')}")
    log(f"  hook: {hook}")
    log(f"  キャッチ: {catch.replace(chr(10), ' / ')}")
    for n in notes:
        log(f"  ⚠ {n}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="物件資料から property.yaml を自動生成")
    ap.add_argument("project", help="物件フォルダ(物件動画/物件名)")
    ap.add_argument("--force", action="store_true", help="既にある property.yaml を作り直す")
    args = ap.parse_args(argv)
    pj = open_project(args.project)
    ok = run_intake(pj, force=args.force)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
