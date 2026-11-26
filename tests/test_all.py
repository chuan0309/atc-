import json
from types import SimpleNamespace

import numpy as np

from atc.app import ATCApp
from atc.brain import ATCBrain, ATCResponse
from atc.config import Config
from atc.gsx import GSX, GSXState
from atc.phases import Phase, PhaseTracker
from atc.sim.mock import MockSim
from atc.simbrief import parse_ofp
from atc.voice.radio_fx import apply_radio_effect

OFP = {
    "general": {"icao_airline": "EVA", "flight_number": "25", "route": "PIANO W4 SALMI",
                "initial_altitude": "36000", "radio_callsign": "EVA"},
    "atc": {"callsign": "EVA25"},
    "aircraft": {"icaocode": "B77W"},
    "origin": {"icao_code": "RCTP", "plan_rwy": "05L", "elevation": "106"},
    "destination": {"icao_code": "RJAA", "plan_rwy": "34L", "elevation": "141"},
    "alternate": {"icao_code": "RJTT"},
    "navlog": {"fix": [
        {"ident": "PIANO", "is_sid_star": "1", "via_airway": "PIANO1", "stage": "CLB"},
        {"ident": "TOC", "is_sid_star": "0", "stage": "CLB"},
        {"ident": "SALMI", "is_sid_star": "0", "via_airway": "W4", "stage": "CRZ"},
        {"ident": "KAIHO", "is_sid_star": "1", "via_airway": "KAIHO1A", "stage": "DSC"},
    ]},
    "weights": {"pax_count": "312"},
}


def test_parse_simbrief():
    p = parse_ofp(OFP)
    assert p.callsign == "EVA25"
    assert p.origin.icao == "RCTP" and p.origin.runway == "05L"
    assert p.destination.icao == "RJAA"
    assert p.sid == "PIANO1" and p.star == "KAIHO1A"
    assert p.cruise_altitude_ft == 36000
    assert p.waypoints == ["PIANO", "SALMI", "KAIHO"]
    assert p.pax == 312


def test_phase_tracker_full_flight():
    sim = MockSim()
    t = PhaseTracker(36000, 141)
    seen = []
    for _ in range(15):
        sim.advance()
        np_ = t.update(sim.get_state())
        if np_:
            seen.append(np_)
    assert seen == [Phase.TAXI_OUT, Phase.TAKEOFF, Phase.DEPARTURE, Phase.CRUISE,
                    Phase.DESCENT, Phase.APPROACH, Phase.LANDING, Phase.TAXI_IN, Phase.PARKED]


def test_phase_never_goes_back():
    t = PhaseTracker(36000)
    t.force(Phase.CRUISE)
    assert not t.force(Phase.TAXI_OUT)
    assert t.phase == Phase.CRUISE


def test_gsx_states_and_pushback():
    sim = MockSim()
    g = GSX(sim)
    sim.lvars["FSDT_GSX_BOARDING_STATE"] = 5
    g.poll()
    sim.lvars["FSDT_GSX_BOARDING_STATE"] = 6
    evs = g.poll()
    assert evs[0].service == "boarding" and evs[0].new == GSXState.COMPLETED
    g.select_by_text = lambda kw, fb, wait=1.0: (sim.set_lvar("FSDT_GSX_MENU_CHOICE", fb) or True)
    assert g.request_pushback()
    assert sim.lvars["FSDT_GSX_MENU_CHOICE"] == 4


def test_gsx_menu_file(tmp_path):
    menu = tmp_path / "menu"
    menu.write_text("Gate 12 - Select\nRequest Deboarding\nRequest Catering\nRequest Pushback\n")
    sim = MockSim()
    g = GSX(sim, str(menu))
    assert g.select_by_text("pushback", wait=0)
    assert sim.lvars["FSDT_GSX_MENU_OPEN"] == 1
    assert sim.lvars["FSDT_GSX_MENU_CHOICE"] == 2


def test_response_parsing_tolerates_fences():
    r = ATCResponse.from_json('```json\n{"respond": true, "controller": "tower", "atc_text": "hi", "x": 1}\n```')
    assert r.respond and r.controller == "tower" and r.atc_text == "hi"


def test_radio_effect_shape():
    pcm = (np.sin(np.linspace(0, 1000, 24000)) * 10000).astype(np.int16).tobytes()
    out = apply_radio_effect(pcm, 24000, seed=1)
    assert len(out) > len(pcm)


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        return SimpleNamespace(text=json.dumps(self.replies.pop(0)))


def _app(replies, **cfgkw):
    cfg = Config(api_key="x", **cfgkw)
    sim = MockSim()
    plan = parse_ofp(OFP)
    models = FakeModels(replies)
    brain = ATCBrain("x", "m", plan, client=SimpleNamespace(models=models))
    out = []
    app = ATCApp(cfg, sim, plan, brain, tts=None, printer=out.append)
    return app, sim, models, out


def test_clearance_then_pushback_calls_gsx():
    app, sim, models, out = _app([
        {"pilot_transcript": "Taipei delivery EVA25 request IFR to Narita", "respond": True,
         "controller": "delivery", "atc_text": "EVA 25 cleared to Narita...", "assigned_squawk": "4521",
         "assigned_altitude_ft": 5000, "handoff_frequency_mhz": 121.7, "handoff_controller": "ground"},
        {"pilot_transcript": "EVA25 request push", "respond": True, "controller": "ground",
         "atc_text": "EVA 25 push and start approved", "approve_pushback": True},
    ])
    pushed = []
    app.gsx.request_pushback = lambda: pushed.append(1) or True
    app.submit_text("Taipei delivery EVA25 request IFR to Narita")
    app.submit_text("EVA25 request push")
    app.drain()
    assert app.brain.memory.squawk == "4521"
    assert app.brain.memory.frequencies["ground"] == 121.7
    assert pushed == [1]
    assert app.tracker.phase == Phase.PUSHBACK
    assert any("DELIVERY" in l for l in out)
    # 第二次呼叫應該帶有歷史
    assert len(models.calls[1]) == 3


def test_frequency_enforcement():
    app, sim, models, out = _app([], require_frequency=True)
    app.brain.memory.expected_frequency = 121.7
    sim.state.com1_active_mhz = 118.1
    app.submit_text("hello")
    app.drain()
    assert models.calls == []
    assert "沒人回你" in out[0]


def test_phase_change_triggers_atc_event():
    app, sim, models, out = _app([
        {"respond": True, "controller": "tower", "atc_text": "EVA 25 contact departure 124.5",
         "handoff_frequency_mhz": 124.5, "handoff_controller": "departure"},
    ])
    app.tracker.force(Phase.TAKEOFF)
    sim.state.on_ground = False
    sim.state.altitude_ft = 2000
    app.tick()
    app.drain()
    assert app.tracker.phase == Phase.DEPARTURE
    assert any("contact departure" in l for l in out)


def test_runway_clearance_reserves_runway():
    from atc.traffic.engine import TrafficManager, TrafficSettings
    from atc.traffic.fsltl import ModelLibrary
    app, sim, models, out = _app([
        {"pilot_transcript": "ready", "respond": True, "controller": "tower",
         "atc_text": "EVA 25 runway 05L cleared for takeoff", "runway_clearance": "takeoff"},
    ])
    app.traffic = TrafficManager(sim, ModelLibrary([]), TrafficSettings(departures_per_hour=0, arrivals_per_hour=0))
    app.submit_text("ready")
    app.drain()
    assert app.traffic.player_reservation == "takeoff"
    # Gemini 有拿到交通狀況
    ctx = models.calls[0][-1].parts[0].text
    assert "AI TRAFFIC" in ctx
