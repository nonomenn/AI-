"""構成の組み立て: 判定済みのカットをテンプレート(見所→広告→部屋紹介→映え+CTA)に当てはめ、30〜40秒に収める。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .analyze import Segment


@dataclass
class Shot:
    section: str                 # hook / catch / ad / start / rooms / cta
    seg: Segment | None          # 動画カット(広告静止画は None)
    src_start: float = 0.0
    duration: float = 0.0        # 出力上の尺(秒)
    speed: float = 1.0
    room: str = ""
    telop: str | None = None     # 表示するテロップID
    telop_span: int = 1          # 何カットにまたがってテロップを出すか(キャッチ用)
    image: str | None = None     # 静止画(広告)
    transition_in: dict = field(default_factory=dict)
    interp: str = ""             # 30fps素材をスローにするときの中間コマの作り方(blend / flow)

    def describe(self):
        if self.image:
            return f"[{self.section:5}] 静止画 {self.image}  {self.duration:.1f}s"
        return (f"[{self.section:5}] {self.seg.id:<20} {self.room:<13} src {self.src_start:5.2f}s"
                f" → {self.duration:.1f}s (x{self.speed})  telop={self.telop or '-'}")


def _speed_for(seg: Segment, cfg) -> float:
    m = cfg["motion"]
    if seg.fps >= m["slow_min_fps"]:
        return m["slow_speed"]
    if m.get("low_fps_interp", "none") != "none":
        return m.get("low_fps_speed", 1.0)   # 30fps素材は中間コマを作ってスローにする(render.py)
    return 1.0


def _room_shot_len(seg: Segment, lo: float, hi: float) -> float:
    """映えるカットほど長く見せる(映え度5以下=lo、9以上=hi)。"""
    k = min(1.0, max(0.0, (seg.beauty - 5.0) / 4.0))
    return lo + (hi - lo) * k


def _usable(seg: Segment) -> bool:
    return not seg.is_transit


def _take(seg: Segment, want: float, cfg, section: str, room: str = "", telop=None) -> Shot:
    """区間から、欲しい尺ぶんを切り出す(区間の中央寄りを使う)。"""
    speed = _speed_for(seg, cfg)
    src_len = min(seg.duration, want * speed)
    dur = src_len / speed
    src_start = seg.start + (seg.duration - src_len) / 2
    m = cfg["motion"]
    interp = m.get("low_fps_interp", "none") if (speed < 1 and seg.fps < m["slow_min_fps"]) else ""
    return Shot(section=section, seg=seg, src_start=round(src_start, 3), duration=round(dur, 3),
                speed=speed, room=room or seg.room, telop=telop, interp=interp if interp != "none" else "")


def build_plan(segs: list[Segment], cfg: dict, tpl: dict, ad_image: str | None, log=print) -> list[Shot]:
    pool = [s for s in segs if _usable(s)]
    used: set[str] = set()

    def pick(prefer: list[str], by_beauty=True, exclude_rooms=()):
        cands = [s for s in pool if s.id not in used and s.room not in exclude_rooms]
        for room in prefer:
            rs = [s for s in cands if s.room == room]
            if rs:
                return max(rs, key=lambda s: (s.beauty, s.score))
        if by_beauty and cands:
            return max(cands, key=lambda s: (s.beauty, s.score))
        return None

    sections = {s["id"]: s for s in tpl["sections"]}
    room_order = sections["rooms"]["order"]
    # 部屋紹介で使うべきカットは、掴み/キャッチに取られないよう先に確保しておく(各部屋のベスト1カット)
    reserved = {}
    for room in room_order:
        rs = [s for s in pool if s.room == room]
        if rs:
            reserved[room] = max(rs, key=lambda s: (s.beauty, s.score)).id

    plan: list[Shot] = []

    def pick_non_reserved(prefer, by_beauty=True, avoid=()):
        saved = set(used)
        used.update(reserved.values())
        s = pick(prefer, by_beauty, exclude_rooms=avoid)
        used.clear(); used.update(saved)
        return s or pick(prefer, by_beauty, exclude_rooms=avoid)

    # --- 先に確保: 映え+CTA(一番映えるカット)と ルームツアーSTART(玄関・廊下)
    cta_sec = sections.get("cta")
    cta_seg = pick_non_reserved(cta_sec["prefer"], avoid=cta_sec.get("avoid", ())) if cta_sec else None
    if cta_seg:
        used.add(cta_seg.id)
    start_sec = sections.get("start")
    start_seg = pick(start_sec["prefer"], by_beauty=False) if start_sec else None
    if start_seg:
        used.add(start_seg.id)

    # --- 見所(hook)
    for sec in tpl["sections"]:
        sid = sec["id"]
        if sid == "hook":
            s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True), sec.get("avoid", ()))
            if s:
                used.add(s.id)
                plan.append(_take(s, sec["duration"], cfg, "hook", telop="hook"))
        elif sid == "catch":
            per = sec["duration"] / sec["shots"]
            first = True
            taken_rooms: list[str] = []
            for _ in range(sec["shots"]):
                avoid = tuple(sec.get("avoid", ())) + (tuple(taken_rooms) if sec.get("distinct_rooms") else ())
                s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True),
                                      avoid + tuple(sec.get("avoid_if_possible", ())))
                if not s:
                    s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True), avoid)
                if not s:
                    break
                used.add(s.id)
                taken_rooms.append(s.room)
                sh = _take(s, per, cfg, "catch", telop="catch" if first else None)
                plan.append(sh)
                first = False
            n = sum(1 for p in plan if p.section == "catch")
            for p in plan:
                if p.section == "catch" and p.telop == "catch":
                    p.telop_span = n
        elif sid == "ad":
            if ad_image:
                plan.append(Shot(section="ad", seg=None, duration=sec["duration"], image=ad_image))
        elif sid == "start":
            if start_seg:
                plan.append(_take(start_seg, sec["duration"], cfg, "start", telop="start"))
        elif sid == "rooms":
            lo, hi = sec["per_shot"]
            for room in room_order:
                n_max = (sec.get("shots_per_room") or {}).get(room, sec["max_shots_per_room"])
                rs = sorted([s for s in pool if s.room == room and s.id not in used],
                            key=lambda s: (s.beauty, s.score), reverse=True)[:n_max]
                # 同じ部屋の中では撮影順に並べる(動きの流れが自然になる)
                rs.sort(key=lambda s: (s.clip, s.start))
                for k, s in enumerate(rs):
                    used.add(s.id)
                    plan.append(_take(s, _room_shot_len(s, lo, hi), cfg, "rooms", room=room,
                                      telop="room" if k == 0 else None))
        elif sid == "cta":
            if cta_seg:
                plan.append(_take(cta_seg, sec["duration"], cfg, "cta", telop="cta"))

    _fit_duration(plan, cfg, tpl, log)
    _assign_transitions(plan, cfg)
    return plan


def _total(plan, cfg):
    tot = sum(p.duration for p in plan)
    tot -= sum(p.transition_in.get("duration", 0) for p in plan[1:])
    return tot


def _fit_duration(plan: list[Shot], cfg, tpl, log):
    """合計尺を 30〜40秒 に合わせる。長ければ 優先度の低い部屋(drop_order) → 部屋の2カット目 の順に削り、
    それでも長ければ部屋カットを均等に短縮。カット数を減らして1カットをゆったり見せるのを優先する。"""
    _assign_transitions(plan, cfg)
    lo, hi = cfg["duration"]["min"], cfg["duration"]["max"]
    rooms_sec = next(s for s in tpl["sections"] if s["id"] == "rooms")
    min_shot = rooms_sec["per_shot"][0]
    # 1) 優先度の低い部屋から丸ごと落とす(部屋が min_rooms 未満にはしない)。
    #    尺が収まっていても、部屋紹介のカット数が max_room_shots を超えていれば落とす(忙しく見えないように)
    drop_order = rooms_sec.get("drop_order", [])
    max_shots = rooms_sec.get("max_room_shots", 99)
    while _total(plan, cfg) > hi or sum(p.section == "rooms" for p in plan) > max_shots:
        present = [p.room for p in plan if p.section == "rooms"]
        victim = next((r for r in drop_order if r in present), None)
        if victim is None or len(set(present)) <= rooms_sec.get("min_rooms", 3):
            break
        plan[:] = [p for p in plan if not (p.section == "rooms" and p.room == victim)]
        _assign_transitions(plan, cfg)
    # 2) 部屋の2カット目を、映え度の低い順に落とす
    while _total(plan, cfg) > hi:
        extras = [p for p in plan if p.section == "rooms" and p.telop is None]
        if not extras:
            break
        worst = min(extras, key=lambda p: (p.seg.beauty, p.seg.score))
        plan.remove(worst)
        _assign_transitions(plan, cfg)
    # 3) それでも長ければ部屋カットを均等に短縮
    while _total(plan, cfg) > hi:
        rooms = [p for p in plan if p.section == "rooms" and p.duration > min_shot]
        if not rooms:
            break
        for p in rooms:
            p.duration = round(max(min_shot, p.duration - 0.2), 3)
    tot = _total(plan, cfg)
    if tot < lo:
        log(f"  ⚠ 使えるカットが少なく、尺が {tot:.1f}秒 になりました(目標 {lo:.0f}〜{hi:.0f}秒)")


def _assign_transitions(plan: list[Shot], cfg):
    tr = cfg["transitions"]
    for i, p in enumerate(plan):
        if i == 0:
            p.transition_in = {}
            continue
        prev = plan[i - 1]
        if p.section == "ad":
            t = tr["to_ad"]
        elif prev.section == "ad":
            t = tr["from_ad"]
        elif p.section == "rooms" and prev.section == "rooms" and p.room == prev.room:
            t = tr["same_room"]
        elif p.section == "catch" and prev.section == "catch":
            t = tr["same_room"]
        elif p.section in ("rooms", "cta", "start") or prev.section in ("rooms", "start"):
            t = tr["room_change"]
        else:
            t = tr["default"]
        # トランジションはカット尺の40%を超えないように
        d = min(t["duration"], 0.4 * min(p.duration, prev.duration))
        p.transition_in = {"type": t["type"], "duration": round(d, 3)}
