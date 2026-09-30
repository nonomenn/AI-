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

    def describe(self):
        if self.image:
            return f"[{self.section:5}] 静止画 {self.image}  {self.duration:.1f}s"
        return (f"[{self.section:5}] {self.seg.id:<20} {self.room:<13} src {self.src_start:5.2f}s"
                f" → {self.duration:.1f}s (x{self.speed})  telop={self.telop or '-'}")


def _speed_for(seg: Segment, cfg) -> float:
    m = cfg["motion"]
    return m["slow_speed"] if seg.fps >= m["slow_min_fps"] else 1.0


def _usable(seg: Segment) -> bool:
    return not seg.is_transit


def _take(seg: Segment, want: float, cfg, section: str, room: str = "", telop=None) -> Shot:
    """区間から、欲しい尺ぶんを切り出す(区間の中央寄りを使う)。"""
    speed = _speed_for(seg, cfg)
    src_len = min(seg.duration, want * speed)
    dur = src_len / speed
    src_start = seg.start + (seg.duration - src_len) / 2
    return Shot(section=section, seg=seg, src_start=round(src_start, 3), duration=round(dur, 3),
                speed=speed, room=room or seg.room, telop=telop)


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
            for _ in range(sec["shots"]):
                s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True), sec.get("avoid", ()))
                if not s:
                    break
                used.add(s.id)
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
                rs = sorted([s for s in pool if s.room == room and s.id not in used],
                            key=lambda s: (s.beauty, s.score), reverse=True)[: sec["max_shots_per_room"]]
                # 同じ部屋の中では撮影順に並べる(動きの流れが自然になる)
                rs.sort(key=lambda s: (s.clip, s.start))
                for k, s in enumerate(rs):
                    used.add(s.id)
                    plan.append(_take(s, hi, cfg, "rooms", room=room, telop="room" if k == 0 else None))
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
    """合計尺を 30〜40秒 に合わせる。長ければ部屋の2カット目から削り、次に各カットを短縮。"""
    _assign_transitions(plan, cfg)
    lo, hi = cfg["duration"]["min"], cfg["duration"]["max"]
    rooms_sec = next(s for s in tpl["sections"] if s["id"] == "rooms")
    min_shot = rooms_sec["per_shot"][0]
    # 1) 部屋の2カット目を、映え度の低い順に落とす
    while _total(plan, cfg) > hi:
        extras = [p for p in plan if p.section == "rooms" and p.telop is None]
        if not extras:
            break
        worst = min(extras, key=lambda p: (p.seg.beauty, p.seg.score))
        plan.remove(worst)
        _assign_transitions(plan, cfg)
    # 2) それでも長ければ部屋カットを均等に短縮
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
