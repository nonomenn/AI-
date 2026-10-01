"""構成の組み立て: 判定済みのカットをテンプレート(見所→広告→部屋紹介→映え+CTA)に当てはめ、30〜45秒に収める。"""
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
    telop_span: int = 1          # 何カットにまたがってテロップを出すか(キャッチ、同じ部屋の2カット目)
    image: str | None = None     # 静止画(広告)
    transition_in: dict = field(default_factory=dict)
    interp: str = ""             # 30fps素材をスローにするときの中間コマの作り方(blend / flow)
    feature: bool = False        # この物件ならではの見どころのカット
    feature_rare: bool = False   # 珍しい見どころ(サウナ・テラス・大理石など)。尺が長くても落とさない
    feature_rank: int = 0        # 見どころの優先順位(property.yaml の highlights の順。0が最優先)

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


def _appeal(s: Segment, highlights: list[dict]) -> float:
    """映え度 + この物件ならではの見どころのボーナス(上位の見どころほど大きい)。冒頭に置くカットを選ぶ基準。"""
    keys = [h["key"] for h in highlights]
    bonus = 0.0
    if s.feature in keys:
        bonus = 3.0 - 0.4 * keys.index(s.feature)
    return s.beauty + max(0.0, bonus) + 0.5 * s.score


def _same_take(a: Segment, b: Segment, gap: float = 6.0) -> bool:
    """同じクリップの、同じ場所を続けて撮った映像の続き(間が gap 秒以内)。
    画角が少しずつ変わるので特徴点では別映像に見えるが、2回使うと「同じ映像の続き」に見える。"""
    if a.clip != b.clip or (a.feature or a.room) != (b.feature or b.room):
        return False
    return max(a.start, b.start) - min(a.end, b.end) <= gap


def _walk_clip(pool: list[Segment]) -> str | None:
    """家の中を歩いて撮った長回し(部屋の種類が一番多いクリップ)。部屋を回る順番の手がかりにする。"""
    by_clip: dict[str, set] = {}
    for s in pool:
        by_clip.setdefault(s.clip, set()).add(s.feature or s.room)
    best = max(by_clip.items(), key=lambda kv: len(kv[1]), default=(None, set()))
    return best[0] if len(best[1]) >= 3 else None


def build_plan(segs: list[Segment], cfg: dict, tpl: dict, ad_image: str | None, log=print,
               highlights: list[dict] | None = None, hook_text: str = "") -> list[Shot]:
    cfg["_zones"] = tpl.get("zones", {})
    highlights = highlights if highlights is not None else cfg.get("_highlights", [])
    cfg["_feature_zone"] = {h["key"]: h.get("near", "") for h in highlights}
    pool = [s for s in segs if _usable(s) and not s.bridge]
    bridges_pool = [s for s in segs if s.bridge]
    used: set[str] = set()
    dup_thr = cfg["analyze"].get("duplicate_inliers", 25)
    chosen: list[Segment] = []          # 実際に使ったカット(同じ構図の2回使いを避けるため)

    def is_dup(s: Segment) -> bool:
        return any(_same_take(s, c) or similarity(s, c) >= dup_thr for c in chosen if c.id != s.id)

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
        rs = [s for s in pool if s.room == room and not s.feature]
        if rs:
            reserved[room] = max(rs, key=lambda s: (s.beauty, s.score)).id
    # 主要な生活空間(LDK・キッチン等)のベストカットは、部屋紹介のために必ず取っておく(冒頭にも使わせない)
    core = next((s_.get("core_rooms", []) for s_ in tpl["sections"] if s_["id"] == "rooms"), [])
    core_keep = [x for x in pool if x.id in {reserved[r] for r in core if r in reserved}]

    def touches_core(x: Segment) -> bool:
        return any(x.id == c.id or _same_take(x, c) or similarity(x, c) >= dup_thr for c in core_keep)

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
            s = None
            # 冒頭テロップが言っている見どころ(例: ガレージ)が映っているカットがあれば、それを最初に見せる
            said = [h["key"] for h in highlights if any(w and w in hook_text for w in h.get("words", []))]
            cands = [x for x in pool if x.feature in said and x.id not in used and not is_dup(x) and not touches_core(x)]
            if cands:
                s = max(cands, key=lambda x: _appeal(x, highlights))
            if not s:
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
                if sec.get("by_appeal"):
                    # 冒頭の数秒は、物件で一番映えるカットを見せて引きを強くする(見どころを優先)
                    cands = [x for x in pool if x.id not in used and not is_dup(x) and not touches_core(x)
                             and (x.feature or x.room) not in avoid and x.room not in sec.get("avoid", ())]
                    s = max(cands, key=lambda x: _appeal(x, highlights)) if cands else None
                else:
                    s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True),
                                          avoid + tuple(sec.get("avoid_if_possible", ())))
                    if not s:
                        s = pick_non_reserved(sec["prefer"], sec.get("by_beauty", True), avoid)
                if not s:
                    break
                used.add(s.id)
                chosen.append(s)
                taken_rooms.append(s.feature or s.room)
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
        elif sid == "common":
            plan.extend(_common(sec, pool, used, chosen, is_dup, highlights, cfg,
                               opening_clips={p.seg.clip for p in plan if p.seg}))
        elif sid == "rooms":
            skip = set(sections["common"]["rooms"]) if "common" in sections else set()
            plan.extend(_tour(sec, pool, bridges_pool, used, chosen, is_dup, dup_thr, highlights, cfg, tpl, log,
                              skip_near=skip))
            missing = [r for r in core if r in reserved and not any(p.room == r for p in plan if p.section == "rooms")]
            if missing:
                log(f"  ⚠ 主要な部屋が部屋紹介に入っていません: {', '.join(missing)}")
        elif sid == "cta":
            if cta_seg:
                plan.append(_take(cta_seg, sec["duration"], cfg, "cta", telop="cta"))

    _fit_duration(plan, cfg, tpl, log)
    _assign_transitions(plan, cfg)
    _carry_room_telops(plan)
    return plan


def _carry_room_telops(plan: list[Shot]) -> None:
    """同じ場所で画角だけ変わるとき(LDKの2カット目など)は、部屋名テロップを消さずに次のカットへ引き継ぐ。
    出し直さず、1つのテロップが続けて表示される(キャッチと同じ telop_span の仕組み)。"""
    for i, p in enumerate(plan):
        if p.telop != "room":
            continue
        n = 1
        while (i + n < len(plan) and plan[i + n].section == p.section and plan[i + n].room == p.room
               and not plan[i + n].telop):
            n += 1
        p.telop_span = n


def _common(sec, pool, used, chosen, is_dup, highlights, cfg, opening_clips=frozenset()) -> list[Shot]:
    """共用部(マンションの外観・緑・エントランス・ロビー)。部屋に入る前に、建物の魅力をまとめて見せる。
    sec["rooms"] の順に並べ、見どころ(near がその場所)はその場所の先頭に入れる。素材が無ければ何も入れない。"""
    places = sec["rooms"]
    lo, hi = sec["per_shot"]
    keys = [h["key"] for h in highlights]
    wanted = [(h["key"], True, (places.index(h["near"]), 0, keys.index(h["key"])))
              for h in highlights if h.get("near") in places]
    wanted += [(r, False, (places.index(r), 1, 0)) for r in places]
    picked = []
    for key, is_feat, order in wanted:
        cands = [x for x in pool if (x.feature == key if is_feat else (x.room == key and not x.feature))
                 and x.id not in used and not is_dup(x)]
        if not cands:
            continue
        # 冒頭(掴み・キャッチ)で使ったクリップの続きより、別のクリップ(別の場所・別の画角)を優先する
        s = max(cands, key=lambda x: (x.clip not in opening_clips, x.beauty, x.score))
        used.add(s.id)
        chosen.append(s)
        picked.append((order, key, is_feat, s))
    # 多すぎるときは、映え度の低いものから省く(珍しい見どころは残す)
    rare = {h["key"] for h in highlights if h.get("rare")}
    while len(picked) > sec.get("max_shots", len(picked)):
        drop = min((p for p in picked if p[1] not in rare), key=lambda p: (p[3].beauty, p[3].score), default=None)
        if drop is None:
            break
        picked.remove(drop)
        used.discard(drop[3].id)
        chosen.remove(drop[3])
    out = []
    for _, key, is_feat, s in sorted(picked, key=lambda p: p[0]):
        sh = _take(s, _room_shot_len(s, lo, hi), cfg, "common", room=key, telop="room")
        sh.feature = is_feat
        out.append(sh)
    return out


def _tour(sec, pool, bridges_pool, used, chosen, is_dup, dup_thr, highlights, cfg, tpl, log,
          skip_near=frozenset()) -> list[Shot]:
    """部屋紹介(ルームツアー)。基本の部屋 + この物件ならではの見どころ(highlights)を、
    歩いて回る順(1F→2F→3F)に並べ、区画が大きく変わるところに廊下・階段のつなぎを入れる。"""
    lo, hi = sec["per_shot"]
    room_order = sec["order"]
    zones = tpl.get("zones", {})
    hl = {h["key"]: h for h in highlights}

    second_gap = sec.get("second_shot_max_gap", 1.0)

    def take_best(cands, n):
        rs = []
        for s in sorted(cands, key=lambda s: (s.beauty, s.score), reverse=True):
            if len(rs) >= n:
                break
            if s.id in used or is_dup(s) or any(_same_take(s, r) or similarity(s, r) >= dup_thr for r in rs):
                continue   # すでに使ったカットと同じ構図・同じ映像の続き → 使わない
            if rs and s.beauty < rs[0].beauty - second_gap:
                break      # 2カット目は、1カット目とほぼ同じくらい映えるときだけ(見劣りするカットで水増ししない)
            rs.append(s)
        return rs

    stops = []   # (key, 見どころか, [カット])
    for room in room_order:
        n_max = (sec.get("shots_per_room") or {}).get(room, sec["max_shots_per_room"])
        rs = take_best([s for s in pool if s.room == room and not s.feature], n_max)
        if rs:
            stops.append((room, False, rs))
    for h in highlights:
        if h.get("in_tour", True) is False or h.get("near") in skip_near:
            continue   # 共用部の見どころは、共用部のパートで見せる
        rs = take_best([s for s in pool if s.feature == h["key"]], 1)
        if rs:
            stops.append((h["key"], True, rs))
        elif not any(s.feature == h["key"] for s in chosen):
            log(f"  ⚠ 見どころ「{h.get('title', h['key'])}」の映像が見つかりません(撮影されていない可能性)")
    for _, _, rs in stops:
        for s in rs:
            used.add(s.id)
            chosen.append(s)

    # 並べる順番: 長回し(家の中を歩いた映像)があれば、その中で出てくる順 = 実際に歩いて回る順
    walk = _walk_clip(pool + bridges_pool) if sec.get("tour_order", "walk") == "walk" else None
    single_rooms = set(sec.get("core_rooms", [])) | {"dining"}

    def pos(stop):
        # 1つしかない部屋(LDK・キッチン等)は、長回しの中で最初に入ったところの順(使うカットが後で撮った別アングルでも)。
        # 洋室・収納などは同じ種類の別の部屋がいくつもあるので、使うカットを撮った位置の順
        key, is_feat, rs = stop
        t = []
        if walk and not is_feat and key in single_rooms:
            t = [s.start for s in pool if s.clip == walk and s.room == key]
        t = t or [s.start for s in rs if s.clip == walk]
        if not t and walk:
            t = [s.start for s in pool if s.clip == walk and (s.feature == key if is_feat else s.room == key)]
        if t:
            return min(t)
        base = hl[key].get("near", "") if is_feat else key
        idx = room_order.index(base) if base in room_order else len(room_order)
        return 1e6 + idx + (0.5 if is_feat else 0)

    stops.sort(key=pos)

    def zone_of(key, is_feat):
        k = hl[key].get("near", key) if is_feat else key
        return next((z for z, rooms in zones.items() if k in rooms), k)

    out: list[Shot] = []
    br = sec.get("bridges", {})
    n_bridges = 0
    prev = None
    for stop in stops:
        key, is_feat, rs = stop
        if (prev and walk and n_bridges < br.get("max", 0)
                and zone_of(prev[0], prev[1]) != zone_of(key, is_feat)):
            # 区画が変わる → その間を歩いた廊下・階段のカットがあれば、ゆったりつなぐ
            a, b = pos(prev), pos(stop)
            cands = [s for s in bridges_pool if s.clip == walk and a < s.start < b and s.id not in used]
            if cands:
                bs = max(cands, key=lambda s: (s.score, -s.speed))
                used.add(bs.id)
                out.append(_take(bs, br.get("duration", 3.0), cfg, "bridge", room=bs.room))
                n_bridges += 1
        rs = sorted(rs, key=lambda s: (s.clip, s.start))   # 同じ部屋の中では撮影順(動きの流れが自然)
        for k, s in enumerate(rs):
            dur = hi if is_feat else _room_shot_len(s, lo, hi)   # 見どころはゆったり長く
            sh = _take(s, dur, cfg, "rooms", room=key, telop="room" if k == 0 else None)
            sh.feature = is_feat
            if is_feat:
                sh.feature_rare = bool(hl[key].get("rare"))
                sh.feature_rank = [h["key"] for h in highlights].index(key)
            out.append(sh)
        prev = stop
    return out


def _total(plan, cfg):
    tot = sum(p.duration for p in plan)
    tot -= sum(p.transition_in.get("duration", 0) for p in plan[1:])
    return tot


def _fit_duration(plan: list[Shot], cfg, tpl, log):
    """合計尺を 30〜45秒 に合わせる。長ければ template.yaml の drop_order の順(トイレ → 収納 → 同じ部屋の2カット目
    → 洗面 …)に削り、それでも長ければ部屋カットを均等に短縮。カット数を減らして1カットをゆったり見せるのを優先する。"""
    _assign_transitions(plan, cfg)
    lo, hi = cfg["duration"]["min"], cfg["duration"]["max"]
    rooms_sec = next(s for s in tpl["sections"] if s["id"] == "rooms")
    min_shot = rooms_sec["per_shot"][0]
    # 1) drop_order の順に落とす(部屋を丸ごと / second_cuts = 同じ部屋の2カット目を映え度の低い順に)。
    #    尺が収まっていても、部屋紹介のカット数が max_room_shots を超えていれば落とす(忙しく見えないように)
    drop_order = rooms_sec.get("drop_order", [])
    max_shots = rooms_sec.get("max_room_shots", 99)
    # 映えにくい部屋(トイレ等)は、部屋紹介が min_rooms に足りないときだけ入れる
    for r in rooms_sec.get("only_if_few", []):
        n_rooms = len({p.room for p in plan if p.section == "rooms"})
        if n_rooms > rooms_sec.get("min_rooms", 0) and any(p.room == r for p in plan if p.section == "rooms"):
            plan[:] = [p for p in plan if not (p.section == "rooms" and p.room == r)]
            log(f"  {r} は省略(映えにくいため。部屋が少ないときだけ入れる)")

    def too_long():
        if sum(p.section == "rooms" for p in plan) > max_shots:
            return True
        # 各カットを少し短くするだけで収まるなら、部屋や見どころを丸ごと落とさない
        slack = sum(max(0.0, p.duration - min_shot) for p in plan if p.section == "rooms")
        return _total(plan, cfg) - slack > hi

    for item in drop_order:
        while too_long():
            if item == "common_features":
                cf = [p for p in plan if p.section == "rooms" and p.feature and not p.feature_rare]
                if not cf:
                    break
                plan.remove(max(cf, key=lambda p: p.feature_rank))
            elif item == "bridges":
                br = [p for p in plan if p.section == "bridge"]
                if not br:
                    break
                plan.remove(br[-1])
            elif item == "second_cuts":
                # 2カット以上ある部屋から、映え度の低い方を落とす(残った方に部屋名テロップを付け直す)
                shots = [p for p in plan if p.section == "rooms" and not p.feature]
                # 主要な部屋の1カット目(ベスト)は落とさない。落とすのは2カット目以降
                firsts = {}
                for p in shots:
                    if p.room not in firsts or (p.seg.beauty, p.seg.score) > (firsts[p.room].seg.beauty, firsts[p.room].seg.score):
                        firsts[p.room] = p
                multi = {r for r in {p.room for p in shots} if sum(q.room == r for q in shots) >= 2}
                extras = [p for p in shots if p.room in multi and firsts.get(p.room) is not p]
                if not extras:
                    break
                worst = min(extras, key=lambda p: (p.seg.beauty, p.seg.score))
                had_telop = worst.telop
                plan.remove(worst)
                if had_telop:
                    next(p for p in plan if p.section == "rooms" and p.room == worst.room).telop = had_telop
            else:
                present = {p.room for p in plan if p.section == "rooms" and not p.feature}
                if (item not in present or item in rooms_sec.get("core_rooms", [])
                        or len(present) <= rooms_sec.get("min_rooms", 3)):
                    break
                plan[:] = [p for p in plan if not (p.section == "rooms" and p.room == item and not p.feature)]
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


def _zone(room: str, zones: dict, feature_near: dict | None = None) -> str:
    room = (feature_near or {}).get(room) or room   # 見どころは、近くの部屋(near)の区画に属する
    return next((z for z, rooms in zones.items() if room in rooms), room)


def _assign_transitions(plan: list[Shot], cfg, zones: dict | None = None):
    """基本はカット。広告の前後・ツアーの始まり・区画の切り替え・最後の見せ場だけ、やわらかく切り替える。"""
    tr = cfg["transitions"]
    zones = zones if zones is not None else cfg.get("_zones", {})
    tol = tr.get("motion_tolerance", 0.06)
    near = cfg.get("_feature_zone", {})
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
        elif prev.section == "start" and p.section in ("rooms", "bridge"):
            t = tr["tour_start"]
        elif prev.section == "common" and p.section == "start":
            t = tr["zone_change"]                             # 共用部 → 住戸へ: 章が変わる
        elif p.section == "bridge":
            t = tr.get("to_bridge", tr["motion_mismatch"])   # 部屋 → 廊下・階段: やわらかく
        elif prev.section == "bridge" and _motion_ok(prev, p, tol):
            t = tr["base"]                                    # 廊下を進んだ先の部屋へ: 歩きの流れのままカット
        elif (p.section == "rooms" and prev.section == "rooms"
              and _zone(p.room, zones, near) != _zone(prev.room, zones, near)):
            t = tr["zone_change"]
        elif _motion_ok(prev, p, tol):
            t = tr["base"]
        else:
            t = tr["motion_mismatch"]
        # トランジションはカット尺の40%を超えないように
        d = min(t["duration"], 0.4 * min(p.duration, prev.duration))
        p.transition_in = {"type": t["type"], "duration": round(d, 3)} if t["type"] != "cut" else {"type": "cut", "duration": 0.0}
