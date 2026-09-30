"""投稿用の文字(動画冒頭テロップ・投稿タイトル・キャプション)と物件番号、納品前チェック。

「不動産テンプレ」のルール:
  - 物件番号は必ず「No.L###」。指定が無ければ 共通/物件番号.txt の次の番号
  - キャプションの1行目は物件番号、2行目に【見出し】、最後に DM 誘導(【L###】と送ってください)
  - ハッシュタグ・家賃・独立した物件情報一覧は出さない
  - サムネイルに物件名を入れない
"""
from __future__ import annotations

import os
import re

NUMBER_RE = re.compile(r"^(?:No\.)?L?(\d{1,4})$", re.I)


def normalize_number(raw) -> str:
    """'L36' / 36 / 'No.L036' → 'L036'"""
    m = NUMBER_RE.match(str(raw).strip())
    if not m:
        raise ValueError(f"物件番号の形式が違います: {raw!r}(例: L036)")
    return f"L{int(m.group(1)):03d}"


def display_number(num: str) -> str:
    return f"No.{num}"


def next_number(counter_path: str | None) -> str:
    """共通/物件番号.txt(最後に使った番号)の次。ファイルが無ければ L001。"""
    if counter_path and os.path.exists(counter_path):
        with open(counter_path, encoding="utf-8") as f:
            last = f.read().strip()
        if last:
            return f"L{int(normalize_number(last)[1:]) + 1:03d}"
    return "L001"


def record_number(counter_path: str | None, num: str):
    """使った番号を記録する(大きい番号だけ残す)。"""
    if not counter_path:
        return
    cur = None
    if os.path.exists(counter_path):
        with open(counter_path, encoding="utf-8") as f:
            cur = f.read().strip() or None
    if cur is None or int(normalize_number(cur)[1:]) < int(num[1:]):
        with open(counter_path, "w", encoding="utf-8") as f:
            f.write(num + "\n")


# ------------------------------------------------------------------ キャプション
RENT_RE = re.compile(r"(賃料|家賃|共益費|管理費|[0-9０-９,，]+\s*円|¥\s*[0-9,]+|万円)")
HASHTAG_RE = re.compile(r"(^|\s)[#＃]\S+")


def build_caption(num: str, heading: str, body: str) -> str:
    body = "\n".join(ln for ln in body.strip().splitlines() if not HASHTAG_RE.search(ln)).strip()
    heading = heading.strip().strip("【】")
    return (f"{display_number(num)}\n\n【{heading}】\n\n{body}\n\n"
            f"気になる方はDMで\n【{num}】と送ってください。\n")


def check_post(num: str, props: dict, caption: str, thumb: dict, property_name: str = "") -> list[str]:
    """納品前チェック。問題があればメッセージのリストを返す(空ならOK)。"""
    probs = []
    lines = caption.splitlines()
    if not lines or lines[0] != display_number(num):
        probs.append("キャプションの1行目が物件番号になっていません")
    if f"【{num}】" not in caption:
        probs.append("CTAの番号がサムネと一致していません")
    if HASHTAG_RE.search(caption):
        probs.append("キャプションにハッシュタグがあります")
    texts = {"キャプション": caption, "投稿タイトル": props.get("post_title", ""),
             "サムネ": " ".join([thumb.get("title", ""), thumb.get("sub", "")] + list(thumb.get("bar", [])))}
    for where, t in texts.items():
        m = RENT_RE.search(t)
        if m:
            probs.append(f"{where}に家賃・金額らしき表記があります: {m.group(0)}")
    if property_name:
        core = re.sub(r"[\s・ー]", "", property_name)
        if core and core in re.sub(r"[\s・ー]", "", texts["サムネ"]):
            probs.append(f"サムネに物件名({property_name})が入っています")
    if len(thumb.get("bar", [])) != 3:
        probs.append("サムネの情報バーは3項目にしてください")
    return probs


def write_post_text(path: str, num: str, props: dict, caption: str, problems: list[str]):
    hook = props.get("hook", "")
    out = [f"■ 物件番号\n{display_number(num)}",
           f"■ 動画冒頭テロップ\n{hook}",
           f"■ 投稿タイトル\n{props.get('post_title', '')}",
           f"■ キャプション\n{caption}"]
    if problems:
        out.append("■ ⚠ 納品前チェックで見つかった点\n" + "\n".join(f"・{p}" for p in problems))
    else:
        out.append("■ 納品前チェック\nOK(番号・CTA一致、ハッシュタグなし、家賃なし、サムネに物件名なし)")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(out) + "\n")
