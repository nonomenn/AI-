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


def test_plan_structure_and_duration(cfg, tpl):
    plan = build_plan(full_pool(), cfg, tpl, "ad.png", log=lambda *_: None)
    sections = [p.section for p in plan]
    order = ["hook", "catch", "ad", "start", "rooms", "cta"]
    assert [s for i, s in enumerate(sections) if i == 0 or sections[i - 1] != s] == order
    _, total = timeline(plan)
    assert cfg["duration"]["min"] <= total <= cfg["duration"]["max"] + 0.01
    # 各部屋のベストカットが部屋紹介に残っている
    rooms = [p.room for p in plan if p.section == "rooms"]
    for r in ["living", "kitchen", "bedroom", "bathroom"]:
        assert r in rooms
    assert "toilet" not in rooms               # 尺が長いときは優先度の低い部屋から落とす
    # drop_order の順に落ちる: 後ろの部屋が残っているなら、前の部屋は落ちている
    order = tpl["sections"][4]["drop_order"]
    kept = [order.index(r) for r in set(rooms) if r in order]
    dropped = [i for i, r in enumerate(order) if r != "second_cuts" and r not in rooms and r in {s.room for s in full_pool()}]
    assert all(d < k for d in dropped for k in kept)
    # 1カットをゆったり見せる(部屋カットは per_shot の下限以上)
    lo = tpl["sections"][4]["per_shot"][0]
    assert all(p.duration >= lo - 0.3 for p in plan if p.section == "rooms")
    # 部屋紹介の順番がテンプレートどおり
    order_idx = [tpl["sections"][4]["order"].index(r) for r in rooms]
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
        elif p.section == "rooms" and prev.section == "rooms" and zone(p.room) != zone(prev.room):
            assert tr["type"] == "blur_dissolve"
        else:  # それ以外はカット(テスト素材は全て動きがそろっている)
            assert tr["type"] == "cut" and tr["duration"] == 0
    assert soft <= 6


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
