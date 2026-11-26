import random

from atc.sim.base import SimState
from atc.sim.mock import MockSim
from atc.traffic.engine import AIState, TrafficManager, TrafficSettings
from atc.traffic.fsltl import Model, ModelLibrary, parse_aircraft_cfg, parse_vmr
from atc.traffic.geo import destination, distance_nm
from atc.traffic.runways import parse_runways, pick_runway
from atc.traffic.speech import say_callsign, say_runway

CSV = '''"id","airport_ref","airport_ident","length_ft","width_ft","surface","lighted","closed","le_ident","le_latitude_deg","le_longitude_deg","le_elevation_ft","le_heading_degT","le_displaced_threshold_ft","he_ident","he_latitude_deg","he_longitude_deg","he_elevation_ft","he_heading_degT","he_displaced_threshold_ft"
239327,5528,"RCTP",12008,197,"CON",1,0,"05L",25.072900772094727,121.21600341796875,73,49.3,,"23R",25.09447479248047,121.24337768554688,62,229.3,
239328,5528,"RCTP",10991,197,"CON",1,0,"05R",25.060842514038086,121.2234878540039,106,49.3,347,"23L",25.08329963684082,121.25199890136719,95,229.3,1167
'''

VMR = '''<?xml version="1.0"?>
<ModelMatchRuleSet>
  <ModelMatchRule CallsignPrefix="CAL" TypeCode="A333" ModelName="FSLTL_A333_CAL-China Airlines" />
  <ModelMatchRule CallsignPrefix="EVA" TypeCode="B77W" ModelName="FSLTL_B77W_EVA-Eva Air//FSLTL_B77W_EVA-Hello Kitty" />
  <ModelMatchRule TypeCode="A320" ModelName="FSLTL_A320_ZZZZ-Generic" />
</ModelMatchRuleSet>'''

CFG = '''[VERSION]
major = 1
[GENERAL]
icao_type_designator = "A321"
[FLTSIM.0]
title = "FSLTL_A321_TTW-Tigerair Taiwan" ; comment
icao_airline = "TTW"
[FLTSIM.1]
title = "FSLTL_A321_ZZZZ"
'''


def rwy():
    return pick_runway(parse_runways(CSV, "RCTP"), "05L")


def test_runways():
    rs = parse_runways(CSV, "RCTP")
    assert [r.ident for r in rs] == ["05L", "23R", "05R", "23L"]
    r = pick_runway(rs, "05L")
    assert r.heading_true == 49.3 and r.length_ft == 12008
    assert abs(distance_nm(r.lat, r.lon, r.end_lat, r.end_lon) - r.length_nm) < 0.1
    assert pick_runway(rs, "99X").length_ft == 12008  # 找不到用最長的


def test_vmr_and_cfg():
    ms = parse_vmr(VMR)
    assert Model("FSLTL_B77W_EVA-Hello Kitty", "B77W", "EVA") in ms
    lib = ModelLibrary(ms + parse_aircraft_cfg(CFG))
    assert lib.match("CAL", "A333").title == "FSLTL_A333_CAL-China Airlines"
    assert lib.match("XXX", "A320").title == "FSLTL_A320_ZZZZ-Generic"
    assert lib.match("TTW", "A321").title == "FSLTL_A321_TTW-Tigerair Taiwan"
    assert lib.match("XXX", "B748") is None


def test_speech():
    assert say_runway("05L") == "zero five left"
    assert say_runway("9") == "zero niner"
    assert say_callsign("Dynasty 123") == "Dynasty one two three"


def _tm(**kw):
    sim = MockSim()
    lib = ModelLibrary(parse_vmr(VMR))
    s = TrafficSettings(departures_per_hour=0, arrivals_per_hour=0, departure_interval_s=0, **kw)
    tm = TrafficManager(sim, lib, s, rng=random.Random(1))
    tm.set_runway(rwy())
    return tm, sim


def far_player():
    return SimState(lat=25.2, lon=121.0, on_ground=True)


def run(tm, p, seconds, dt=0.5):
    for _ in range(int(seconds / dt)):
        tm.update(p, dt)


def test_departure_lifecycle():
    tm, sim = _tm()
    a = tm.spawn_departure()
    assert a.object_id in sim.ai and a.title.startswith("FSLTL_")
    run(tm, far_player(), 400)
    texts = [c.text for c in tm.pop_radio()]
    assert any("ready for departure" in t for t in texts)
    assert any("line up and wait" in t for t in texts)
    assert any("cleared for takeoff" in t for t in texts)
    assert any("contact departure" in t for t in texts)
    assert tm.aircraft == [] and sim.ai == {}


def test_arrival_lands_when_clear():
    tm, sim = _tm()
    a = tm.spawn_arrival(8)
    states = set()
    for _ in range(600):
        tm.update(far_player(), 0.5)
        if tm.aircraft:
            states.add(tm.aircraft[0].state)
    texts = [c.text for c in tm.pop_radio()]
    assert any("cleared to land" in t for t in texts)
    assert AIState.ROLLOUT in states and AIState.GO_AROUND not in states
    assert tm.aircraft == []


def test_arrival_goes_around_when_player_on_runway():
    tm, sim = _tm()
    r = tm.runway
    lat, lon = destination(r.lat, r.lon, r.heading_true, 0.3)
    player = SimState(lat=lat, lon=lon, on_ground=True)
    assert tm.player_on_runway(player)
    tm.spawn_arrival(5)
    run(tm, player, 200)
    texts = [c.text for c in tm.pop_radio()]
    assert any("go around" in t for t in texts)
    assert not any("cleared to land" in t for t in texts)


def test_departure_waits_for_player_on_final():
    tm, sim = _tm()
    r = tm.runway
    lat, lon = destination(r.lat, r.lon, (r.heading_true + 180) % 360, 4)
    player = SimState(lat=lat, lon=lon, on_ground=False, altitude_agl_ft=1300)
    assert 3.9 < tm.player_final_nm(player) < 4.1
    a = tm.spawn_departure()
    run(tm, player, 60)
    assert a.state == AIState.HOLDING_SHORT
    assert "departure: holding short" in tm.summary(player)


def test_player_reservation_blocks_lineup():
    tm, sim = _tm()
    tm.player_reservation = "takeoff"
    a = tm.spawn_departure()
    run(tm, far_player(), 30)
    assert a.state == AIState.HOLDING_SHORT
    assert "takeoff clearance" in tm.summary(far_player())


def test_random_spawning_respects_limits():
    tm, sim = _tm()
    tm.s.departures_per_hour = 3600
    tm.s.arrivals_per_hour = 3600
    run(tm, far_player(), 20)
    holding = [a for a in tm.aircraft if a.state == AIState.HOLDING_SHORT]
    finals = [a for a in tm.aircraft if a.arrival]
    assert len(holding) <= 2 and len(finals) <= 2


def test_set_runway_change_clears_traffic():
    tm, sim = _tm()
    tm.spawn_departure()
    tm.set_runway(None)
    assert tm.aircraft == [] and sim.ai == {}
