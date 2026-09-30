"""物件フォルダ(物件動画/物件名/)から、素材・物件資料・共通素材(広告・BGM・書体)の場所を解決する。

フォルダ構成は config/project.yaml を参照。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_layout() -> dict:
    with open(os.path.join(HERE, "config/project.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _has_ext(name: str, exts) -> bool:
    return os.path.splitext(name)[1].lower() in exts


def _files(d: str, exts) -> list[str]:
    if not d or not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d)
                  if not f.startswith(".") and _has_ext(f, exts) and os.path.isfile(os.path.join(d, f)))


@dataclass
class Project:
    root: str
    name: str
    clips: list[str]
    docs: list[str]
    property_path: str
    floorplan_path: str
    facts_path: str
    out_dir: str
    common_dir: str | None
    ad: str | None = None
    bgms: list[str] = field(default_factory=list)
    font_dir: str | None = None
    thumb_photo: str | None = None

    @property
    def out_video(self) -> str:
        return os.path.join(self.out_dir, f"{self.name}.mp4")

    def pick_bgm(self, wanted: str | None) -> str | None:
        """property.yaml の bgm(ファイル名 or パス)→ 実在パス。未指定は名前順で先頭。"""
        if wanted:
            for b in self.bgms:  # 共通/BGM/ の中から、拡張子の有無を問わず名前で探す
                if os.path.splitext(os.path.basename(b))[0] == os.path.splitext(os.path.basename(wanted))[0]:
                    return b
            for p in (os.path.join(self.root, wanted), wanted):
                if os.path.isfile(p):
                    return p
            raise FileNotFoundError(f"BGM '{wanted}' が見つかりません(共通/BGM/ を確認)")
        return self.bgms[0] if self.bgms else None


def open_project(root: str, layout: dict | None = None) -> Project:
    L = layout or load_layout()
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"物件フォルダがありません: {root}")
    name = os.path.basename(root.rstrip(os.sep))
    mat = os.path.join(root, L["materials_dir"])
    clips = _files(mat, L["video_ext"])
    files = _files(root, L["doc_ext"])
    thumb_words = [w.lower() for w in L.get("thumb_photo_words", [])]
    is_thumb = [any(w in os.path.basename(f).lower() for w in thumb_words) and f.lower().endswith(tuple(L["image_ext"]))
                for f in files]
    docs = [f for f, t in zip(files, is_thumb) if not t]
    thumb_photo = next((f for f, t in zip(files, is_thumb) if t), None)

    common = os.path.normpath(os.path.join(root, L["common_dir"]))
    common = common if os.path.isdir(common) else None
    ad = None
    bgms: list[str] = []
    font_dir = None
    if common:
        imgs = _files(common, L["image_ext"])
        for stem in L["common"]["ad"]:
            ad = next((p for p in imgs if os.path.splitext(os.path.basename(p))[0] == stem), None)
            if ad:
                break
        for dn in L["common"]["bgm_dir"]:
            bgms = _files(os.path.join(common, dn), L["audio_ext"])
            if bgms:
                break
        for dn in L["common"]["font_dir"]:
            if os.path.isdir(os.path.join(common, dn)):
                font_dir = os.path.join(common, dn)
                break

    return Project(
        root=root, name=name, clips=clips, docs=docs,
        property_path=os.path.join(root, L["property_file"]),
        floorplan_path=os.path.join(root, L["floorplan_file"]),
        facts_path=os.path.join(root, L["facts_file"]),
        out_dir=os.path.join(root, L["output_dir"]),
        common_dir=common, ad=ad, bgms=bgms, font_dir=font_dir, thumb_photo=thumb_photo,
    )
