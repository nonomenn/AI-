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
    assert rooms.count("living") == 2          # 主役の部屋は2カット
    assert "toilet" not in rooms               # 尺が長いときは優先度の低い部屋から落とす
    # 1カットをゆったり見せる(部屋カットは per_shot の下限以上)
    lo = tpl["sections"][4]["per_shot"][0]
    assert all(p.duration >= lo - 0.3 for p in plan if p.section == "rooms")
    # 部屋紹介の順番がテンプレートどおり
    order_idx = [tpl["sections"][4]["order"].index(r) for r in rooms]
    assert order_idx == sorted(order_idx)


def test_transitions(cfg, tpl):
    plan = build_plan(full_pool(), cfg, tpl, "ad.png", log=lambda *_: None)
    for prev, p in zip(plan, plan[1:]):
        tr = p.transition_in
        assert tr["duration"] <= 0.4 * min(p.duration, prev.duration) + 1e-6
        assert tr["type"] in ("dissolve", "blur_dissolve", "fade_white", "fade_black", "cut")
        if p.section == "ad" or prev.section == "ad":
            assert tr["type"] == "fade_white"
        elif p.section == "rooms" and prev.section == "rooms":
            assert tr["type"] == ("dissolve" if p.room == prev.room else "blur_dissolve")


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
