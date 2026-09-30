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
    for r in ["living", "dining", "kitchen", "bedroom", "bathroom", "toilet"]:
        assert r in rooms
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


def test_slow_motion_only_for_60fps(cfg, tpl):
    pool = [seg(0, "living", fps=60), seg(1, "kitchen", fps=30), seg(2, "balcony", fps=60)]
    plan = build_plan(pool, cfg, tpl, None, log=lambda *_: None)
    for p in plan:
        assert p.speed == (cfg["motion"]["slow_speed"] if p.seg.fps >= 50 else 1.0)


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
