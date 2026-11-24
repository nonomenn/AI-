"""売上・経費の記録(revenue/ledger.csv)から、プロジェクト別・月別のまとめを作る。

使い方: python3 tools/revenue_summary.py
出力:   revenue/サマリー.md

ledger.csv の書き方(1行1件):
  日付,プロジェクト,種類,金額,内容,メモ
  2026-12-01,制作代行,売上,10000,A社 動画1本,
  2026-12-01,制作代行,経費,1500,交通費,
  種類は「売上」か「経費」。金額は円の整数(カンマ無し)。
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER = BASE / "revenue" / "ledger.csv"
OUT = BASE / "revenue" / "サマリー.md"


def load(path):
    rows, errors = [], []
    with open(path, encoding="utf-8", newline="") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            try:
                kind = r["種類"].strip()
                if kind not in ("売上", "経費"):
                    raise ValueError(f"種類が「{kind}」")
                rows.append({
                    "month": r["日付"].strip()[:7],
                    "project": r["プロジェクト"].strip(),
                    "kind": kind,
                    "amount": int(r["金額"].strip().replace(",", "")),
                })
            except (ValueError, KeyError, AttributeError) as e:
                errors.append(f"{i}行目: {e}")
    return rows, errors


def yen(n):
    return f"{n:,}円"


def build(rows, errors):
    total = defaultdict(lambda: {"売上": 0, "経費": 0})
    monthly = defaultdict(lambda: {"売上": 0, "経費": 0})
    for r in rows:
        total[r["project"]][r["kind"]] += r["amount"]
        monthly[(r["month"], r["project"])][r["kind"]] += r["amount"]

    lines = ["# 売上サマリー", "", "`revenue/ledger.csv` から自動で作成。手で編集しない。", ""]
    if errors:
        lines += ["## 読めなかった行", ""] + [f"- {e}" for e in errors] + [""]
    if not rows:
        lines += ["まだ記録がありません。", ""]
        return "\n".join(lines)

    lines += ["## プロジェクト別(累計)", "", "| プロジェクト | 売上 | 経費 | 手残り |", "|---|---|---|---|"]
    s_all = e_all = 0
    for p in sorted(total):
        s, e = total[p]["売上"], total[p]["経費"]
        s_all += s
        e_all += e
        lines.append(f"| {p} | {yen(s)} | {yen(e)} | {yen(s - e)} |")
    lines += [f"| **合計** | **{yen(s_all)}** | **{yen(e_all)}** | **{yen(s_all - e_all)}** |", ""]

    lines += ["## 月別", "", "| 月 | プロジェクト | 売上 | 経費 | 手残り |", "|---|---|---|---|---|"]
    for (m, p) in sorted(monthly, reverse=True):
        s, e = monthly[(m, p)]["売上"], monthly[(m, p)]["経費"]
        lines.append(f"| {m} | {p} | {yen(s)} | {yen(e)} | {yen(s - e)} |")
    lines.append("")
    lines.append("※ 手残りは税金を引く前の金額")
    return "\n".join(lines) + "\n"


def main():
    ledger = Path(sys.argv[1]) if len(sys.argv) > 1 else LEDGER
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT
    rows, errors = load(ledger)
    out.write_text(build(rows, errors), encoding="utf-8")
    print(f"{out} を更新しました({len(rows)}件、読めない行 {len(errors)}件)")


if __name__ == "__main__":
    main()
