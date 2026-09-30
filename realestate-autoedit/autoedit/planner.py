"""構成の組み立て: 判定済みのカットをテンプレート(見所→広告→部屋紹介→映え+CTA)に当てはめ、30〜40秒に収める。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .analyze import Segment, similarity


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
    """再生速度。基本 0.8倍。カメラが速く動いているカットほど、さらにスローにする(下限は fps で変える)。"""
    m = cfg["motion"]
    hi_fps = seg.fps >= m["slow_min_fps"]
    if hi_fps:
        base, floor = m["slow_speed"], m.get("adaptive_slow", {}).get("min_speed_60fps", m["slow_speed"])
    elif m.get("low_fps_interp", "none") != "none":   # 30fps素材は中間コマを作ってスローにする(render.py)
        base, floor = m.get("low_fps_speed", 1.0), m.get("adaptive_slow", {}).get("min_speed_30fps", 1.0)
    else:
        return 1.0
    ad = m.get("adaptive_slow")
    if ad and seg.speed > 0:
        return round(max(floor, min(base, ad["target_speed"] / seg.speed)), 2)
    return base


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
    cfg["_zones"] = tpl.get("zones", {})
    pool = [s for s in segs if _usable(s)]
    used: set[str] = set()
    dup_thr = cfg["analyze"].get("duplicate_inliers", 25)
    chosen: list[Segment] = []          # 実際に使ったカット(同じ構図の2回使いを避けるため)

    def is_dup(s: Segment) -> bool:
        return any(similarity(s, c) >= dup_thr for c in chosen if c.id != s.id)

    def pick(prefer: list[str], by_beauty=True, exclude_rooms=()):
        cands = [s for s in pool if s.id not in used and s.room not in exclude_rooms and not is_dup(s)]
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
        """部屋紹介用に確保したカット(と、それと同じ構図のカット)は、ほかに候補があれば使わない。"""
        saved, n_chosen = set(used), len(chosen)
        used.update(reserved.values())
        chosen.extend(s_ for s_ in pool if s_.id in reserved.values())
        s = pick(prefer, by_beauty, exclude_rooms=avoid)
        used.clear(); used.update(saved)
        del chosen[n_chosen:]
        return s or pick(prefer, by_beauty, exclude_rooms=avoid)

    # --- 先に確保: 映え+CTA(一番映えるカット)と ルームツアーSTART(玄関・廊下)
    cta_sec = sections.get("cta")
    cta_seg = pick_non_reserved(cta_sec["prefer"], avoid=cta_sec.get("avoid", ())) if cta_sec else None
    if cta_seg:
        used.add(cta_seg.id)
        chosen.append(cta_seg)
    start_sec = sections.get("start")
    start_seg = pick(start_sec["prefer"], by_beauty=False) if start_sec else None
    if start_seg:
        used.add(start_seg.id)
        chosen.append(start_seg)

    # --- 見所(hook)
    for sec in tpl["sections"]:
        sid = sec["id"]
        if sid == "hook":
            s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True), sec.get("avoid", ()))
            if s:
                used.add(s.id)
                chosen.append(s)
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
                chosen.append(s)
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
                rs = []
                for s in sorted([s for s in pool if s.room == room and s.id not in used],
                                key=lambda s: (s.beauty, s.score), reverse=True):
                    if len(rs) >= n_max:
                        break
                    if is_dup(s) or any(similarity(s, r) >= dup_thr for r in rs):
                        continue   # すでに使ったカットと同じ構図 → 使わない
                    rs.append(s)
                # 同じ部屋の中では撮影順に並べる(動きの流れが自然になる)
                rs.sort(key=lambda s: (s.clip, s.start))
                for k, s in enumerate(rs):
                    used.add(s.id)
                    chosen.append(s)
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
    """合計尺を 30〜40秒 に合わせる。長ければ template.yaml の drop_order の順(トイレ → 収納 → 同じ部屋の2カット目
    → 洗面 …)に削り、それでも長ければ部屋カットを均等に短縮。カット数を減らして1カットをゆったり見せるのを優先する。"""
    _assign_transitions(plan, cfg)
    lo, hi = cfg["duration"]["min"], cfg["duration"]["max"]
    rooms_sec = next(s for s in tpl["sections"] if s["id"] == "rooms")
    min_shot = rooms_sec["per_shot"][0]
    # 1) drop_order の順に落とす(部屋を丸ごと / second_cuts = 同じ部屋の2カット目を映え度の低い順に)。
    #    尺が収まっていても、部屋紹介のカット数が max_room_shots を超えていれば落とす(忙しく見えないように)
    drop_order = rooms_sec.get("drop_order", [])
    max_shots = rooms_sec.get("max_room_shots", 99)

    def too_long():
        return _total(plan, cfg) > hi or sum(p.section == "rooms" for p in plan) > max_shots

    for item in drop_order:
        while too_long():
            if item == "second_cuts":
                # 2カット以上ある部屋から、映え度の低い方を落とす(残った方に部屋名テロップを付け直す)
                shots = [p for p in plan if p.section == "rooms"]
                multi = {r for r in {p.room for p in shots} if sum(q.room == r for q in shots) >= 2}
                extras = [p for p in shots if p.room in multi]
                if not extras:
                    break
                worst = min(extras, key=lambda p: (p.seg.beauty, p.seg.score))
                had_telop = worst.telop
                plan.remove(worst)
                if had_telop:
                    next(p for p in plan if p.section == "rooms" and p.room == worst.room).telop = had_telop
            else:
                present = {p.room for p in plan if p.section == "rooms"}
                if item not in present or len(present) <= rooms_sec.get("min_rooms", 3):
                    break
                plan[:] = [p for p in plan if not (p.section == "rooms" and p.room == item)]
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


def _motion_ok(a: Shot, b: Shot, tol: float) -> bool:
    """カットでつないでも自然か(前後で横の動きの向きがそろっているか、どちらかがほぼ止まっているか)。"""
    if not a.seg or not b.seg:
        return False
    ax, bx = a.seg.direction[0], b.seg.direction[0]
    return abs(ax) < tol or abs(bx) < tol or (ax > 0) == (bx > 0)


def _zone(room: str, zones: dict) -> str:
    return next((z for z, rooms in zones.items() if room in rooms), room)


def _assign_transitions(plan: list[Shot], cfg, zones: dict | None = None):
    """基本はカット。広告の前後・ツアーの始まり・区画の切り替え・最後の見せ場だけ、やわらかく切り替える。"""
    tr = cfg["transitions"]
    zones = zones if zones is not None else cfg.get("_zones", {})
    tol = tr.get("motion_tolerance", 0.06)
    for i, p in enumerate(plan):
        if i == 0:
            p.transition_in = {}
            continue
        prev = plan[i - 1]
        if p.section == "ad":
            t = tr["to_ad"]
        elif prev.section == "ad":
            t = tr["from_ad"]
        elif p.section == "cta":
            t = tr["to_cta"]
        elif prev.section == "start" and p.section == "rooms":
            t = tr["tour_start"]
        elif (p.section == "rooms" and prev.section == "rooms"
              and _zone(p.room, zones) != _zone(prev.room, zones)):
            t = tr["zone_change"]
        elif _motion_ok(prev, p, tol):
            t = tr["base"]
        else:
            t = tr["motion_mismatch"]
        # トランジションはカット尺の40%を超えないように
        d = min(t["duration"], 0.4 * min(p.duration, prev.duration))
        p.transition_in = {"type": t["type"], "duration": round(d, 3)} if t["type"] != "cut" else {"type": "cut", "duration": 0.0}
