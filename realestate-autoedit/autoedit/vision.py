"""AI判定(Claude API): 各カットに何が映っているか(部屋の種類・映え度)と、間取り図の読み取り。

- ANTHROPIC_API_KEY(または ant auth login の認証)があれば Claude の画像認識で判定する
- 使えないとき、または --labels で手動ラベルが渡されたときは、ファイル名のキーワードで判定する(フォールバック)
- 応答は JSON スキーマ指定(structured outputs)で受け取り、壊れたJSONで止まらないようにしている
- モデルは環境変数 AUTOEDIT_MODEL で変えられる
"""
from __future__ import annotations

import base64
import json
import os

import cv2
import yaml

from .analyze import Segment
from .media import grab_frame

DEFAULT_MODEL = os.environ.get("AUTOEDIT_MODEL", "claude-opus-5-5")
# 安全判定で断られたとき、サーバー側で別モデルに回す(Claude API 直結のときのみ有効。Bedrock等では AUTOEDIT_NO_FALLBACK=1)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# 間取り図に載らないことが多い/建物側の種類。間取り図による制限の対象外にする
ALWAYS_ALLOWED = ["exterior", "entrance_hall", "genkan", "corridor", "closet", "view", "other"]

ROOM_KEYWORDS = {
    "exterior": ["外観", "exterior", "facade", "gaikan"],
    "entrance_hall": ["エントランス", "共用", "lobby", "entrance_hall"],
    "genkan": ["玄関", "genkan"],
    "corridor": ["廊下", "corridor", "hall"],
    "living": ["リビング", "ldk", "living"],
    "dining": ["ダイニング", "dining"],
    "kitchen": ["キッチン", "kitchen"],
    "bedroom": ["寝室", "bedroom"],
    "western_room": ["洋室", "room"],
    "japanese_room": ["和室", "washitsu"],
    "closet": ["クローゼット", "収納", "closet", "wic"],
    "washroom": ["洗面", "脱衣", "wash", "powder"],
    "bathroom": ["浴室", "風呂", "bath"],
    "toilet": ["トイレ", "toilet", "wc"],
    "balcony": ["バルコニー", "ベランダ", "balcony"],
    "view": ["眺望", "view"],
}


class VisionError(RuntimeError):
    pass


def ai_available() -> bool:
    """APIを使える認証情報があるか(キー、トークン、ant auth login のプロファイル)。"""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))


def _jpeg_b64(frame, width=640):
    h = int(frame.shape[0] * width / frame.shape[1])
    small = cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return base64.b64encode(buf.tobytes()).decode()


def image_block(frame, long_side=1568) -> dict:
    """画像(numpy BGR)→ Claude の image ブロック。長辺を long_side 以下に縮める。"""
    h, w = frame.shape[:2]
    width = w if max(w, h) <= long_side else int(w * long_side / max(w, h))
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": _jpeg_b64(frame, width)}}


def file_blocks(path: str) -> list[dict]:
    """物件資料ファイル(PDF・画像)→ Claude のコンテンツブロック。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        return [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                 "title": os.path.basename(path)}]
    img = cv2.imdecode(_read_bytes(path), cv2.IMREAD_COLOR)  # 日本語パス対策で imdecode
    if img is None:
        raise VisionError(f"画像を読めません: {path}")
    return [image_block(img)]


def _read_bytes(path):
    import numpy as np
    return np.fromfile(path, dtype=np.uint8)


def _client():
    import anthropic  # 遅延import(APIを使わない場合は不要)
    return anthropic.Anthropic()


def ask_json(content: list[dict], schema: dict, model: str = DEFAULT_MODEL, max_tokens: int = 16000,
             client=None) -> dict:
    """画像・資料 + 指示を送り、schema どおりの JSON を dict で受け取る。"""
    import anthropic
    client = client or _client()
    kw = dict(model=model, max_tokens=max_tokens,
              output_config={"format": {"type": "json_schema", "schema": schema}},
              messages=[{"role": "user", "content": content}])
    use_fb = not os.environ.get("AUTOEDIT_NO_FALLBACK")
    try:
        if use_fb:
            msg = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kw)
        else:
            msg = client.messages.create(**kw)
    except anthropic.BadRequestError as e:
        if not use_fb or "fallback" not in str(e).lower():
            raise
        msg = client.messages.create(**kw)  # フォールバック非対応の環境
    if msg.stop_reason == "refusal":
        raise VisionError("AIが判定を断りました(refusal)")
    if msg.stop_reason == "max_tokens":
        raise VisionError("AIの応答が途中で切れました(max_tokens)")
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise VisionError(f"AIの応答をJSONとして読めません: {text[:200]}") from e


# ------------------------------------------------------------------ 間取り図
ROOM_TYPE_ENUM = ["exterior", "entrance_hall", "genkan", "corridor", "living", "dining", "kitchen", "bedroom",
                  "western_room", "japanese_room", "closet", "washroom", "bathroom", "toilet", "balcony", "other"]

FLOORPLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "layout": {"type": "string"},
        "rooms": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "type": {"type": "string", "enum": ROOM_TYPE_ENUM},
                           "size_jo": {"type": "number"}},
            "required": ["name", "type", "size_jo"], "additionalProperties": False}},
    },
    "required": ["found", "layout", "rooms"], "additionalProperties": False,
}

FLOORPLAN_RULES = """間取り図の読み方:
- layout は「2LDK」などの間取りタイプ(読めなければ空文字)
- rooms は図面上の部屋を全て。name は図面の表記(例: LDK 12.5帖、洋室1、浴室)、size_jo は帖数(無ければ 0)
- LDK は living 1件とし、ダイニング・キッチンが一体なら dining / kitchen も併記してよい
- 洗面脱衣所は washroom、ユニットバス・浴室は bathroom、WIC・CL・収納は closet、ベランダは balcony"""


def read_floorplan(image_path: str, model: str = DEFAULT_MODEL, client=None) -> dict:
    content = file_blocks(image_path) + [{"type": "text", "text":
        "これは賃貸/分譲物件の間取り図です。読み取れる部屋を全て列挙してください。\n" + FLOORPLAN_RULES
        + "\n間取り図が写っていなければ found=false にしてください。"}]
    return ask_json(content, FLOORPLAN_SCHEMA, model, max_tokens=4000, client=client)


def allowed_rooms(room_types: list[str], floorplan: dict | None) -> list[str]:
    """間取り図があれば、そこに無い部屋の種類を判定候補から外す。"""
    if not floorplan or not floorplan.get("rooms"):
        return list(room_types)
    have = {r.get("type") for r in floorplan["rooms"]}
    if "living" in have or "LDK" in (floorplan.get("layout") or "").upper():
        have |= {"living", "dining", "kitchen"}
    # 寝室と洋室は図面の表記ゆれが大きいので、どちらかがあれば両方許す
    if have & {"bedroom", "western_room"}:
        have |= {"bedroom", "western_room"}
    return [r for r in room_types if r in have or r in ALWAYS_ALLOWED]


def _coerce_room(room: str, allowed: list[str]) -> str:
    if room in allowed:
        return room
    swap = {"bedroom": "western_room", "western_room": "bedroom", "dining": "living", "kitchen": "living"}
    return swap[room] if swap.get(room) in allowed else "other"


# ------------------------------------------------------------------ カット判定
CLASSIFY_PROMPT = """不動産ルームツアー動画の素材から切り出したカットです。各カットにつき3コマ(始め・中・終わり)を添付しています。
添付した全カットについて、カットIDごとに判定してください。

room は次から選ぶ: {room_types}
{floorplan_hint}
beauty(0〜10)の基準: 高級感・明るさ・構図の美しさ・その物件の魅力(眺望、デザイン照明、広さ)が伝わるか。
is_transit: ドアを通過中、壁や床しか映っていない、部屋から部屋への移動途中など「見せ場ではない」カットなら true。
same_room: 3コマすべてで、その部屋が主役として映っているなら true。途中で廊下・ドア・別の部屋に移る
(例: 廊下を歩いて洗面所に入る途中)なら false。false のカットには部屋名テロップを付けず、使わない。
note: 10文字程度の内容メモ。"""


def _classify_schema(room_types):
    return {
        "type": "object",
        "properties": {"cuts": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "room": {"type": "string", "enum": room_types},
                           "beauty": {"type": "number"}, "is_transit": {"type": "boolean"},
                           "same_room": {"type": "boolean"}, "note": {"type": "string"}},
            "required": ["id", "room", "beauty", "is_transit", "same_room", "note"],
            "additionalProperties": False}}},
        "required": ["cuts"], "additionalProperties": False,
    }


def classify_segments(segs: list[Segment], room_types: list[str], floorplan: dict | None = None,
                      model: str = DEFAULT_MODEL, batch: int = 6, log=print, client=None) -> None:
    """Segment.room / beauty / is_transit / note をAIで埋める(破壊的更新)。
    失敗したまとまりは、ファイル名キーワードでの判定に切り替えて先に進む。"""
    allowed = allowed_rooms(room_types, floorplan)
    hint = ""
    if floorplan and floorplan.get("rooms"):
        names = ", ".join(f'{r["name"]}({r["type"]})' for r in floorplan["rooms"])
        hint = f"この物件の間取り({floorplan.get('layout', '')}): {names}\n間取りに無い部屋の種類は選ばないこと。"
        dropped = sorted(set(room_types) - set(allowed))
        if dropped:
            log(f"  間取り図に無いため判定候補から除外: {', '.join(dropped)}")
    prompt = CLASSIFY_PROMPT.replace("{room_types}", ", ".join(allowed)).replace("{floorplan_hint}", hint)
    schema = _classify_schema(allowed)
    client = client or _client()
    for b in range(0, len(segs), batch):
        chunk = segs[b:b + batch]
        content = []
        for s in chunk:
            content.append({"type": "text", "text": f"カットID: {s.id}"})
            for t in (s.start + 0.1, s.mid, s.end - 0.1):
                f = grab_frame(s.clip, t)
                if f is not None:
                    content.append(image_block(f, 512))
        content.append({"type": "text", "text": prompt})
        try:
            res = ask_json(content, schema, model, max_tokens=4000, client=client)
        except Exception as e:  # noqa: BLE001 — 1まとまりの失敗で全体を止めない
            log(f"  ⚠ AI判定に失敗({type(e).__name__}: {str(e)[:120]})。このまとまりはファイル名で判定")
            label_from_filename(chunk)
            continue
        by_id = {r.get("id"): r for r in res.get("cuts", []) if isinstance(r, dict)}
        for s in chunk:
            r = by_id.get(s.id)
            if not r:
                label_from_filename([s])
                continue
            s.room = _coerce_room(r.get("room", "other"), allowed)
            s.beauty = max(0.0, min(10.0, float(r.get("beauty", 5))))
            s.is_transit = bool(r.get("is_transit", False)) or not r.get("same_room", True)
            s.note = str(r.get("note", "")) + ("" if r.get("same_room", True) else " (途中で場所が変わる→不使用)")
        log(f"  AI判定 {min(b + batch, len(segs))}/{len(segs)} カット")


# ------------------------------------------------------------------ フォールバック
def label_from_filename(segs: list[Segment]) -> None:
    for s in segs:
        name = os.path.basename(s.clip).lower()
        for room, kws in ROOM_KEYWORDS.items():
            if any(k.lower() in name for k in kws):
                s.room = room
                break


def apply_manual_labels(segs: list[Segment], labels_path: str, min_len: float = 1.5, pad: float = 0.3) -> None:
    """手動ラベル(labels.yaml)の適用。
    書式:
      clip_02.mp4: dining                    # クリップ全体
      walkthrough_01.mp4:                    # 時間範囲ごと
        - {from: 0, to: 6, room: genkan, beauty: 6}
        - {from: 6, to: 9, room: kitchen}
    """
    with open(labels_path, encoding="utf-8") as f:
        labels = yaml.safe_load(f) or {}
    for s in segs:
        spec = labels.get(os.path.basename(s.clip))
        if spec is None:
            continue
        if isinstance(spec, str):
            s.room = spec
            continue
        for r in spec:
            if r["from"] <= s.mid < r["to"]:
                # カットが範囲からはみ出していたら、範囲の内側だけに縮める
                # (はみ出した部分には別の場所=廊下など が映っているため。はみ出したまま部屋名を付けない)
                s.start = round(max(s.start, r["from"] + (pad if s.start < r["from"] else 0)), 2)
                s.end = round(min(s.end, r["to"] - (pad if s.end > r["to"] else 0)), 2)
                if s.end - s.start < min_len:
                    s.is_transit = True
                    s.note = (r.get("note", "") + " 短すぎるため不使用").strip()
                    break
                s.room = r["room"]
                s.beauty = float(r.get("beauty", s.beauty))
                s.is_transit = bool(r.get("transit", False))
                s.note = r.get("note", "")
                break
