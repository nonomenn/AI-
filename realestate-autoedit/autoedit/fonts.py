"""書体ファイルの解決。

style.yaml の fonts には、ファイル名(またはパス)を候補の順に並べる。
  1. 絶対パス / カレントからの相対パスで存在すればそれを使う
  2. 物件動画/共通/フォント/ → assets/fonts/ → OS の書体フォルダ の順にファイル名で探す
見つからない候補は飛ばし、どれも無ければエラーにする(黙って別の書体にしない)。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM_FONT_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    "/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
]
FONT_EXT = (".ttf", ".ttc", ".otf", ".otc")


class FontNotFound(RuntimeError):
    pass


def _index(dirs: list[str]) -> dict[str, str]:
    """ファイル名(小文字) → パス。先に並んだフォルダを優先する。"""
    idx: dict[str, str] = {}
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(FONT_EXT):
                    idx.setdefault(f.lower(), os.path.join(root, f))
    return idx


def font_dirs(common_font_dir: str | None = None) -> list[str]:
    dirs = [common_font_dir] if common_font_dir else []
    return dirs + [os.path.join(HERE, "assets", "fonts")] + SYSTEM_FONT_DIRS


def resolve_fonts(spec: dict, common_font_dir: str | None = None, log=print) -> dict[str, str]:
    """{役割: 候補(文字列 or リスト)} → {役割: 実在するパス}"""
    idx = None
    out = {}
    for role, cands in spec.items():
        cands = [cands] if isinstance(cands, str) else list(cands)
        found = None
        for c in cands:
            c = os.path.expanduser(str(c))
            if os.path.isfile(c):
                found = c
                break
            if idx is None:
                idx = _index(font_dirs(common_font_dir))
            p = idx.get(os.path.basename(c).lower())
            if p:
                found = p
                break
        if not found:
            raise FontNotFound(
                f"書体 '{role}' が見つかりません(候補: {', '.join(map(str, cands))})。"
                f"物件動画/共通/フォント/ か assets/fonts/ に置くか、style.yaml の fonts を直してください")
        if found != cands[0] and os.path.basename(found).lower() != os.path.basename(str(cands[0])).lower():
            log(f"  書体 {role}: 第1候補が無いため {os.path.basename(found)} を使用")
        out[role] = found
    return out


if __name__ == "__main__":  # python -m autoedit.fonts [共通フォントフォルダ]
    import yaml
    cfg = yaml.safe_load(open(os.path.join(HERE, "config/style.yaml"), encoding="utf-8"))
    for k, v in resolve_fonts(cfg["fonts"], sys.argv[1] if len(sys.argv) > 1 else None).items():
        print(f"{k:12} {v}")
