from autoedit.analyze import Segment
from autoedit.planner import build_plan
from autoedit.render import timeline


def seg(i, room, beauty=7, dur=6.0, fps=60.0):
    return Segment(clip=f"/x/{room}_{i}.mp4", start=0.2, end=0.2 + dur, fps=fps, width=1080, height=1920,
                   score=0.8, room=room, beauty=beauty, id=f"{room}_{i}#0")


def full_pool():
    rooms = ["exterior", "entrance_hall", "entrance_hall", "genkan", "corridor", "living", "living", "living",
             "dining", "kitchen", "kitchen", "bedroom", "bedroom", "western_room", "closet", "washroom",
             "bathroom", "bathroom", "toilet", "balcony", "view"]
    return [seg(i, r, beauty=5 + (i % 5)) for i, r in enumerate(rooms)]


def _sec(tpl, sid):
    return next(s for s in tpl["sections"] if s["id"] == sid)


def test_plan_structure_and_duration(cfg, tpl):
    plan = build_plan(full_pool(), cfg, tpl, "ad.png", log=lambda *_: None)
    sections = [p.section for p in plan]
    order = ["hook", "catch", "ad", "common", "start", "rooms", "cta"]
    assert [s for i, s in enumerate(sections) if i == 0 or sections[i - 1] != s] == order
    _, total = timeline(plan)
    assert cfg["duration"]["min"] <= total <= cfg["duration"]["max"] + 0.01
    # 各部屋のベストカットが部屋紹介に残っている
    rooms = [p.room for p in plan if p.section == "rooms"]
    for r in ["living", "kitchen", "bedroom", "bathroom"]:
        assert r in rooms
    assert "toilet" not in rooms               # 尺が長いときは優先度の低い部屋から落とす
    # drop_order の順に落ちる: 後ろの部屋が残っているなら、前の部屋は落ちている
    order = _sec(tpl, "rooms")["drop_order"]
    kept = [order.index(r) for r in set(rooms) if r in order]
    opening = {p.room for p in plan if p.section in ("hook", "catch")}   # 冒頭で使った部屋は「落とした」に数えない
    dropped = [i for i, r in enumerate(order) if r != "second_cuts" and r not in rooms and r not in opening
               and r in {s.room for s in full_pool()}]
    assert all(d < k for d in dropped for k in kept)
    # 1カットをゆったり見せる(部屋カットは per_shot の下限以上)
    lo = _sec(tpl, "rooms")["per_shot"][0]
    assert all(p.duration >= lo - 0.3 for p in plan if p.section == "rooms")
    # 部屋紹介の順番がテンプレートどおり
    order_idx = [_sec(tpl, "rooms")["order"].index(r) for r in rooms]
    assert order_idx == sorted(order_idx)


def test_transitions(cfg, tpl):
    """基本はカット。広告の前後・ツアー開始・区画の切り替え・最後の見せ場だけやわらかく。"""
    plan = build_plan(full_pool(), cfg, tpl, "ad.png", log=lambda *_: None)
    zones = tpl["zones"]
    zone = lambda r: next((z for z, rs in zones.items() if r in rs), r)
    soft = 0
    for prev, p in zip(plan, plan[1:]):
        tr = p.transition_in
        assert tr["duration"] <= 0.4 * min(p.duration, prev.duration) + 1e-6
        if tr["type"] != "cut":
            soft += 1
        if p.section == "ad" or prev.section == "ad":
            assert tr["type"] == "dissolve"
        elif p.section == "cta":
            assert tr["type"] == "light_leak"
        elif prev.section == "start" and p.section == "rooms":
            assert tr["type"] == "blur_dissolve"
        elif prev.section == "common" and p.section == "start":
            assert tr["type"] == "blur_dissolve"           # 共用部 → 住戸: 章の切れ目
        elif p.section == "rooms" and prev.section == "rooms" and zone(p.room) != zone(prev.room):
            assert tr["type"] == "blur_dissolve"
        else:  # それ以外はカット(テスト素材は全て動きがそろっている)
            assert tr["type"] == "cut" and tr["duration"] == 0
    assert soft <= 7   # 章の切れ目(広告の前後・共用部→住戸・ツアー開始・区画・最後)だけ


def test_motion_mismatch_uses_dissolve(cfg, tpl):
    from autoedit.planner import Shot, _assign_transitions
    a, b, c = seg(0, "living"), seg(1, "living"), seg(2, "living")
    a.direction, b.direction, c.direction = (0.25, 0, 0), (-0.25, 0, 0), (-0.20, 0, 0)  # 右へ → 左へ → 左へ
    plan = [Shot("rooms", s_, duration=4.0, room="living") for s_ in (a, b, c)]
    _assign_transitions(plan, cfg, tpl["zones"])
    assert plan[1].transition_in["type"] == "dissolve"   # 向きが逆 → やわらかく
    assert plan[2].transition_in["type"] == "cut"        # 向きがそろう → カット


def test_adaptive_slow(cfg, tpl):
    fast, slow = seg(0, "living"), seg(1, "kitchen")
    fast.speed, slow.speed = 0.30, 0.10   # 画面幅/秒
    plan = build_plan([fast, slow, seg(2, "balcony")], cfg, tpl, None, log=lambda *_: None)
    sp = {p.seg.id: p.speed for p in plan if p.seg}
    assert sp[fast.id] == 0.5 and sp[slow.id] == 0.8   # 速いカットほど遅く(60fpsの下限0.5)


def test_slow_motion(cfg, tpl):
    import copy
    pool = [seg(0, "living", fps=60), seg(1, "kitchen", fps=30), seg(2, "balcony", fps=60)]
    plan = build_plan(pool, cfg, tpl, None, log=lambda *_: None)
    for p in plan:  # 60fps はそのままスロー、30fps は中間コマを作ってスロー
        assert p.speed == 0.8
        assert p.interp == ("" if p.seg.fps >= 50 else "blend")
    c2 = copy.deepcopy(cfg)
    c2["motion"]["low_fps_interp"] = "none"
    plan = build_plan(pool, c2, tpl, None, log=lambda *_: None)
    for p in plan:
        assert p.speed == (0.8 if p.seg.fps >= 50 else 1.0) and p.interp == ""


def test_transit_and_water_rules(cfg, tpl):
    pool = full_pool()
    pool[5].is_transit = True  # living_5
    plan = build_plan(pool, cfg, tpl, None, log=lambda *_: None)
    assert all(p.seg.id != pool[5].id for p in plan if p.seg)
    hook = next(p for p in plan if p.section == "hook")
    assert hook.room not in ("bathroom", "toilet", "washroom", "closet")


def test_short_material_warns(cfg, tpl):
    msgs = []
    build_plan([seg(0, "living", dur=2.0)], cfg, tpl, None, log=msgs.append)
    assert any("尺" in m for m in msgs)


def test_no_duplicate_composition(cfg, tpl):
    """別ファイルでも同じ映像(同じ場所・同じ向き)は2回使わない(リビングの同じ映像2回使い対策)。"""
    import cv2
    import numpy as np
    from autoedit.analyze import signature_from_image, similarity
    rng = np.random.default_rng(0)
    tex = cv2.GaussianBlur((rng.random((700, 420)) * 255).astype(np.uint8), (0, 0), 1.2)
    other = cv2.GaussianBlur((rng.random((700, 420)) * 255).astype(np.uint8), (0, 0), 1.2)
    a, b, c = seg(0, "living", beauty=9), seg(1, "living", beauty=8), seg(2, "living", beauty=7)
    a.sig = signature_from_image(tex[0:640, 0:360])
    b.sig = signature_from_image(tex[12:652, 20:380])     # 少しずれた同じ映像
    c.sig = signature_from_image(other[0:640, 0:360])     # 別の映像
    assert similarity(a, b) >= 25 and similarity(a, c) < 25
    pool = [a, b, c, seg(3, "exterior"), seg(4, "balcony"), seg(5, "corridor")]
    plan = build_plan(pool, cfg, tpl, None, log=lambda *_: None)
    ids = [p.seg.id for p in plan if p.seg and p.room == "living"]
    assert a.id in ids and b.id not in ids and c.id in ids


def _walk_seg(i, room, t, beauty=6, feature="", bridge=False, clip="/x/walk.mov"):
    s = Segment(clip=clip, start=t, end=t + 5.0, fps=60.0, width=1080, height=1920, score=0.85,
                room=room, beauty=beauty, id=f"w#{i}")
    s.feature, s.bridge = feature, bridge
    return s


def test_highlights_bridges_and_opening(cfg, tpl):
    """見どころは部屋紹介に入り(珍しいものは落とさない)、区画が変わるところに廊下のつなぎ、冒頭は一番映えるカット。"""
    hl = [{"key": "sauna", "title": "Sauna", "near": "bathroom", "rare": True, "words": ["サウナ"]},
          {"key": "pantry", "title": "Pantry", "near": "kitchen", "rare": False, "words": []}]
    pool = [_walk_seg(0, "genkan", 0), _walk_seg(1, "corridor", 6),
            _walk_seg(2, "washroom", 12), _walk_seg(3, "bathroom", 18, feature="sauna", beauty=8),
            _walk_seg(4, "bathroom", 24), _walk_seg(5, "corridor", 30, bridge=True),
            _walk_seg(6, "living", 36, beauty=9), _walk_seg(7, "kitchen", 42, beauty=8),
            _walk_seg(8, "closet", 48, feature="pantry"), _walk_seg(9, "western_room", 54),
            seg(10, "balcony", beauty=7), seg(11, "exterior", beauty=6), seg(12, "living", beauty=10)]
    plan = build_plan(pool, cfg, tpl, "ad.png", log=lambda *_: None, highlights=hl, hook_text="サウナ付きの新築")
    secs = [(p.section, p.room) for p in plan]
    assert secs[0] == ("hook", "bathroom") and plan[0].seg.feature == "sauna"  # 冒頭テロップが言う見どころを最初に
    catch = [p for p in plan if p.section == "catch"]
    assert catch[0].seg.beauty >= 9                       # キャッチは一番映えるカット
    tour = [(p.section, p.room) for p in plan if p.section in ("rooms", "bridge")]
    assert any(p.seg and p.seg.feature == "sauna" for p in plan)   # 珍しい見どころ(サウナ)は必ず映る
    assert ("bridge", "corridor") in tour                  # 水回り → LDK の区画の変わり目に廊下
    i = tour.index(("bridge", "corridor"))
    assert tour[i - 1][1] in ("washroom", "bathroom") and tour[i + 1][1] in ("living", "kitchen")
    _, total = timeline(plan)
    assert total <= cfg["duration"]["max"] + 0.01


def test_core_rooms_keep_their_best_shot(cfg, tpl):
    """LDK・キッチンは必ず部屋紹介に入り、その一番映えるカットは冒頭(キャッチ)に取られない。"""
    best_ldk, other_ldk = seg(0, "living", beauty=9), seg(1, "living", beauty=6)
    best_kit, other_kit = seg(2, "kitchen", beauty=9), seg(3, "kitchen", beauty=6)
    pool = [best_ldk, other_ldk, best_kit, other_kit, seg(4, "exterior", beauty=7), seg(5, "balcony", beauty=7),
            seg(6, "corridor"), seg(7, "bathroom", beauty=7), seg(8, "western_room", beauty=7)]
    plan = build_plan(pool, cfg, tpl, "ad.png", log=lambda *_: None)
    tour = {p.seg.id for p in plan if p.section == "rooms"}
    opening = {p.seg.id for p in plan if p.section in ("hook", "catch")}
    assert best_ldk.id in tour and best_kit.id in tour
    assert best_ldk.id not in opening and best_kit.id not in opening
    # 2カット目は見劣りするなら使わない(映え度 6 < 9-1)
    assert other_ldk.id not in tour and other_kit.id not in tour


def test_common_area_before_tour(cfg, tpl):
    """マンションの共用部(外観・緑・エントランス・ロビー)は、部屋に入る前にまとめて見せる。
    冒頭で使ったクリップの続きより、別のクリップを優先する。"""
    hl = [{"key": "lobby", "title": "Lobby", "near": "entrance_hall", "rare": True, "words": []},
          {"key": "tower", "title": "Tower", "near": "exterior", "words": []}]
    lobby_a, lobby_b = seg(0, "entrance_hall", beauty=9), seg(1, "entrance_hall", beauty=8)
    lobby_a.feature = lobby_b.feature = "lobby"
    lobby_a2 = Segment(clip=lobby_a.clip, start=7.0, end=13.0, fps=60.0, width=1080, height=1920, score=0.8,
                       room="entrance_hall", beauty=9, id="lobby_a#1")
    lobby_a2.feature = "lobby"
    tower = seg(2, "exterior", beauty=8)
    tower.feature = "tower"
    pool = [lobby_a, lobby_a2, lobby_b, tower, seg(3, "exterior", beauty=6), seg(4, "entrance_hall", beauty=6),
            seg(5, "corridor"), seg(6, "living", beauty=9), seg(7, "kitchen", beauty=8),
            seg(8, "western_room"), seg(9, "balcony", beauty=8), seg(10, "view", beauty=9)]
    plan = build_plan(pool, cfg, tpl, "ad.png", log=lambda *_: None, highlights=hl)
    secs = [p.section for p in plan]
    assert secs.index("ad") < secs.index("common") < secs.index("start") < secs.index("rooms")
    common = [p for p in plan if p.section == "common"]
    assert all(p.telop == "room" for p in common)
    assert [p.room for p in common][-2:] == ["lobby", "entrance_hall"]   # 外観 → エントランス(見どころが先)
    opening_clips = {p.seg.clip for p in plan if p.section in ("hook", "catch")}
    lob = next(p for p in common if p.room == "lobby")
    assert lob.seg.clip not in opening_clips                             # 冒頭と同じクリップの続きは避ける
    assert not any(p.room in ("lobby", "tower") for p in plan if p.section == "rooms")


def test_window_only_shots_are_not_used(tmp_path, cfg, tpl):
    """窓辺に寄って窓・ブラインドだけを写した画角は、映え度が高くても使わない。"""
    from autoedit import vision
    lab = tmp_path / "labels.yaml"
    lab.write_text("walk.mov:\n  - {from: 0, to: 8, room: living, beauty: 9, window_only: true}\n"
                   "  - {from: 8, to: 16, room: living, beauty: 7}\n", encoding="utf-8")
    mk = lambda a, b: Segment(clip="/x/walk.mov", start=a, end=b, fps=60, width=1080, height=1920,
                              score=0.8, id=f"w{a}")
    win, room = mk(1.0, 7.0), mk(9.0, 15.0)
    vision.apply_manual_labels([win, room], str(lab))
    assert win.is_transit and not room.is_transit
    pool = [win, room, seg(1, "kitchen"), seg(2, "exterior"), seg(3, "corridor"), seg(4, "balcony")]
    plan = build_plan(pool, cfg, tpl, None, log=lambda *_: None)
    assert all(p.seg.id != win.id for p in plan if p.seg)
