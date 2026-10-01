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
        "built": {"type": "string"},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "hook_candidates": {"type": "array", "items": {"type": "string"}},
        "catch_candidates": {"type": "array", "items": {"type": "string"}},
        "highlights": {"type": "array", "items": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "title": {"type": "string"}, "sub": {"type": "string"},
                           "near": {"type": "string"}, "words": {"type": "array", "items": {"type": "string"}},
                           "rare": {"type": "boolean"}},
            "required": ["key", "title", "sub", "near", "words", "rare"], "additionalProperties": False}},
        "thumb_title": {"type": "string"},
        "thumb_sub": {"type": "string"},
        "thumb_bar": {"type": "array", "items": {"type": "string"}},
        "post_title": {"type": "string"},
        "caption_heading": {"type": "string"},
        "caption_body": {"type": "string"},
    },
    "required": ["property_name", "building_type", "station", "line", "walk_minutes", "layout", "area_m2",
                 "features", "floorplan", "built", "conditions", "highlights", "hook_candidates", "catch_candidates",
                 "thumb_title", "thumb_sub", "thumb_bar", "post_title", "caption_heading", "caption_body"],
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
 - built: 築年月・竣工(例: 2026年8月竣工)。conditions: ペット・SOHO・階数・方角などの条件(資料にあるものだけ)

2. floorplan: 間取り図の読み取り。source には間取り図が載っていたファイル名(PDFならファイル名とページ)。
{floorplan_rules}

2b. highlights: この物件ならではの見どころを、魅力の大きい順に最大6つ(資料に書かれているものだけ)。
 動画では基本の部屋(リビング・キッチン等)とは別に、これを映像から探して必ず見せる。
 - key: 次の決まった名前から選ぶ。合うものが無ければ英小文字とアンダースコアで新しく作る
   garage, shoe_closet(土間収納), pantry, laundry, walk_in_closet, sauna, terrace, roof_balcony, private_garden,
   marble(大理石の天板など), island_kitchen, atrium(吹き抜け), view(眺望)
 - title: 部屋紹介テロップの英字(例: Garage, Pantry)。sub: 明朝のサブコピー(全角16文字以内、上品に)
 - near: いちばん近い部屋の種類(genkan, living, kitchen, bedroom, washroom, bathroom, balcony など)
 - words: 冒頭テロップ等でこの見どころを指す言葉(例: ["ガレージ"])
 - rare: 賃貸ではなかなかない特徴なら true(サウナ、屋外テラス、ルーフバルコニー、専用庭、大理石、ガレージ、吹き抜け、
   アイランドキッチン、眺望など)。土間収納・パントリー・WIC・ランドリーなど比較的よくあるものは false

3〜4. 冒頭(0〜9秒)のコピー。目的は「この物件は何が特別か」を1つだけ伝えて、続きを見たくさせること。
 まず訴求ポイントを1つ決める。選ぶ順:
   (1) 賃貸では珍しい希少性(ガレージ、大型犬OK、サウナ、専用庭、メゾネット、タワー高層階、眺望 など)
   (2) 数字のインパクト(専有100㎡超、LDK20帖超、駅徒歩5分以内、30階以上 など)
   (3) 立地のブランド(梅田・北浜・心斎橋・本町 など、名前だけで伝わるエリア)
   (4) 新築・デザイン性
 使わないもの: 弱みになる数字(徒歩10分超、築年数が古い)、設備の羅列、どの物件にも言える言葉(素敵なお部屋 等)
 hook_candidates: 動画冒頭テロップ(0〜3秒・1行・全角14文字以内)を、次の3つの型で1案ずつ、この順に:
   [0] 憧れの暮らし型: その物件で叶う暮らしを一言で。例「愛犬と、ガレージのある新築へ。」
   [1] 問いかけ・意外性型: 見る人の予想を裏切る。例「賃貸で、この広さ。」
   [2] 数字の断言型: いちばん強い数字を言い切る。例「148㎡、新築の4LDK。」
 catch_candidates: hook の直後に出すキャッチ(2行、改行は \\n。各行 全角12文字以内)を3案。hook の言葉を事実で裏付ける
   - 1行目=誰に/どこで/一番の希少ワード、2行目=何が(物件種別+特徴)
   - 一番刺さる希少ワードを《》で1か所だけ囲む(その文字の上に傍点が付き、点滅する)
   - 例: 「《大型犬OK》の\\n新築ガレージハウス」「《阿波座駅》3分の\\nデザイナーズマンション」
   - 資料に無い事実は書かない。徒歩分数・駅名は資料どおり
 サムネのタイトルも同じ訴求ポイントで作る(動画冒頭とサムネで言っていることをそろえる)

5. サムネイル(黒×ゴールドの固定テンプレートに入れる文言。デザインは変えない)
 - thumb_title: 1行・全角16文字以内。その物件で一番訴求力の高い特徴(駅徒歩・立地・新築・高層階・眺望・広さ・
   タワーマンション・サウナなどの希少設備・デザイン・ペット可など)を、スクロールを止める上品なコピーに。
   ゴールドにする語を《》で囲む(1〜2か所)。例: 「《北浜エリア駅徒歩6分》の好立地。」「《31階の高層階》×《南向き》の開放感。」
 - thumb_sub: 1行・全角22文字以内の白い補足。例: 「充実設備のハイグレードレジデンス。」
 - thumb_bar: 情報バーの3項目。各 全角9文字以内。例: ["個室サウナ付き", "26畳の広々リビング", "駅徒歩6分"]
 - サムネには物件名(建物名)を絶対に入れない
6. post_title: 投稿タイトル。短く、エリア・駅・新築・広さなど検索されやすい語を自然に入れる
7. キャプション
 - caption_heading: 【】の中に入る見出し。例: 「大阪・梅田｜31階から望む新築タワーレジデンス」
 - caption_body: 本文。駅・徒歩分数、新築・築年月、間取り・面積、特徴、条件を、SEOを意識しつつ自然な文章で。
   キーワードの不自然な羅列は禁止。物件番号・見出し・DM誘導はこちらで付けるので本文に書かない
 - ハッシュタグ・家賃・独立した物件情報一覧は書かない
 - 「神物件」「ヤバすぎる」「住まないと損」などの安っぽい煽りは禁止。高級賃貸アカウントとしての品を保つ

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

    hooks, fit = pick(facts.get("hook_candidates", []), lambda s: s.strip().replace("\n", ""), 14)
    if hooks and not fit:
        notes.append("hook がどの案も14文字を超えています(自動で縮小して表示されます)")
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
    out += ["# number: L036        # 物件番号。未指定なら 共通/物件番号.txt の次の番号",
            f"hook: {_q(hook)}   # 動画冒頭テロップ",
            f"catch: {_q(catch)}   # 《》で囲んだ文字の上に傍点(●)。\\n で改行",
            'cta: "気になった方は詳細とコメント"']
    if others:
        out.append("# ほかの案:")
        out += [f"#   {o.replace(chr(10), ' / ')}" for o in others]
    if facts and facts.get("highlights"):
        out += ["", "# この物件ならではの見どころ(上ほど優先)。映像の中から探して、部屋紹介でゆったり見せる",
                "highlights:"]
        for h in facts["highlights"]:
            out.append("  - " + json.dumps({k: h[k] for k in ("key", "title", "sub", "near", "words", "rare") if k in h},
                                            ensure_ascii=False))
    if facts:
        bar = [b.strip() for b in facts.get("thumb_bar", [])][:3]
        out += ["", "# サムネイル(《》で囲んだ部分がゴールド)",
                "thumbnail:",
                f"  title: {_q(facts.get('thumb_title', ''))}",
                f"  sub: {_q(facts.get('thumb_sub', ''))}",
                f"  bar: {json.dumps(bar, ensure_ascii=False)}",
                "  # photo: サムネ写真.jpg   # 物件フォルダ内の写真。未指定なら自動で選ぶ",
                "", f"post_title: {_q(facts.get('post_title', ''))}",
                f"caption_heading: {_q(facts.get('caption_heading', '').strip('【】'))}",
                "caption: |"]
        out += ["  " + ln if ln.strip() else "" for ln in (facts.get("caption_body") or "").strip().splitlines()]
        out.append("")
        out.append("# 資料から読み取った物件情報(確認用。動画には直接使わない)")
        info = {k: facts.get(k) for k in ("property_name", "building_type", "station", "line", "walk_minutes",
                                           "layout", "area_m2", "built", "features", "conditions")}
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
