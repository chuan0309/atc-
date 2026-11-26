import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atc.sim.base import SimState
from atc.sim.mock import MockSim
from atc.traffic.airports import AirportPos, parse_airports
from atc.traffic.enroute import EnrouteTraffic, position_at
from atc.traffic.engine import TrafficManager, TrafficSettings
from atc.traffic.fsltl import ModelLibrary, parse_vmr
from atc.traffic.schedule import (CSVScheduleProvider, Schedule, ScheduledFlight, model_to_icao,
                                  parse_aerodatabox, parse_schedule_csv)
from test_traffic import VMR, rwy

UTC = timezone.utc
T0 = datetime(2026, 11, 26, 1, 0, tzinfo=UTC)


def test_model_to_icao():
    assert model_to_icao("Airbus A330-300") == "A333"
    assert model_to_icao("Boeing 777-300ER") == "B77W"
    assert model_to_icao("Boeing 737-800") == "B738"
    assert model_to_icao("Airbus A321neo") == "A21N"
    assert model_to_icao("Boeing 787-9") == "B789"
    assert model_to_icao("Airbus A350-900") == "A359"
    assert model_to_icao("A359") == "A359"
    assert model_to_icao("Mystery jet") == ""


def test_parse_aerodatabox():
    data = {
        "departures": [{
            "number": "CI 100", "callSign": "CAL100", "status": "Expected",
            "airline": {"name": "China Airlines", "iata": "CI", "icao": "CAL"},
            "aircraft": {"model": "Airbus A330-300", "reg": "B-18301"},
            "departure": {"airport": {"icao": "RCTP"}, "scheduledTime": {"utc": "2026-11-26 00:30Z", "local": "x"}},
            "arrival": {"airport": {"icao": "RJAA", "iata": "NRT"}, "scheduledTime": {"utc": "2026-11-26 03:45Z"}},
        }, {
            "number": "BR 999", "status": "Canceled", "airline": {"icao": "EVA"},
            "departure": {"scheduledTime": {"utc": "2026-11-26 01:00Z"}}, "arrival": {"airport": {"icao": "RJAA"}},
        }],
        "arrivals": [{
            "number": "JL 802", "airline": {"icao": "JAL"}, "aircraft": {"model": "Boeing 787-8"},
            "departure": {"airport": {"icao": "RJAA"}},
            "arrival": {"scheduledTime": {"utc": "2026-11-26 04:30Z"}, "revisedTime": {"utc": "2026-11-26 04:40Z"}},
        }],
    }
    fl = parse_aerodatabox(data, "RCTP")
    assert len(fl) == 2
    ci, jl = fl
    assert (ci.callsign, ci.type_code, ci.origin, ci.destination) == ("CAL100", "A333", "RCTP", "RJAA")
    assert ci.dep_utc == datetime(2026, 11, 26, 0, 30, tzinfo=UTC)
    assert ci.arr_utc == datetime(2026, 11, 26, 3, 45, tzinfo=UTC)
    assert (jl.callsign, jl.type_code, jl.origin, jl.destination) == ("JAL802", "B788", "RJAA", "RCTP")
    assert jl.arr_utc == datetime(2026, 11, 26, 4, 40, tzinfo=UTC)  # revised 優先


def test_csv_schedule_and_merge(tmp_path):
    csv = Path(__file__).parent.parent / "schedule.example.csv"
    fl = parse_schedule_csv(csv.read_text(), T0)
    cal = next(f for f in fl if f.callsign == "CAL100")
    assert cal.type_code == "A333" and cal.dep_utc == T0.replace(hour=0, minute=30)
    s = Schedule(CSVScheduleProvider(csv).fetch_all(T0))
    assert len(s) == 3 * len(fl)  # 昨天/今天/明天
    s.add(ScheduledFlight("CAL100", "CAL", "100", "", "RCTP", "RJAA", cal.dep_utc, cal.arr_utc))
    assert len(s) == 3 * len(fl)  # 重複的不會多算
    assert [f.callsign for f in s.departures("RCTP")][:3] == ["CAL100", "EVA178", "TTW200"]


def test_overnight_csv():
    fl = parse_schedule_csv("callsign,type,origin,destination,dep_utc,arr_utc\nUAL872,B789,KSFO,RCTP,23:30,10:30\n", T0)
    assert fl[0].arr_utc - fl[0].dep_utc == timedelta(hours=11)


def _sched_tm(flights, now):
    clock = {"t": now}
    tm = TrafficManager(MockSim(), ModelLibrary(parse_vmr(VMR)),
                        TrafficSettings(departure_interval_s=0), rng=random.Random(1),
                        schedule=Schedule(flights), clock=lambda: clock["t"])
    tm.set_runway(rwy())
    return tm, clock


def test_schedule_spawns_real_flights_at_right_time():
    dep = ScheduledFlight("EVA178", "EVA", "178", "B77W", "RCTP", "RJAA", T0, T0 + timedelta(hours=3))
    arr = ScheduledFlight("CAL101", "CAL", "101", "A333", "RJAA", "RCTP", T0 - timedelta(hours=3), T0 + timedelta(minutes=30))
    tm, clock = _sched_tm([dep, arr], T0)
    p = SimState(lat=25.3, lon=121.0)
    tm.update(p, 1)
    assert tm.aircraft == []  # 還沒到時間
    clock["t"] = T0 + timedelta(minutes=9)
    tm.update(p, 1)
    assert [a.callsign for a in tm.aircraft] == ["EVA178"]
    a = tm.aircraft[0]
    assert a.radio == "Eva 178" and a.type_code == "B77W" and "EVA" in a.title  # 對到 EVA 777 塗裝
    clock["t"] = T0 + timedelta(minutes=27)
    tm.update(p, 1)
    assert "CAL101" in [x.callsign for x in tm.aircraft]
    n = len(tm.aircraft)
    tm.update(p, 1)  # 不會重複生
    assert len(tm.aircraft) == n


def test_expired_schedule_not_spawned():
    dep = ScheduledFlight("EVA178", "EVA", "178", "B77W", "RCTP", "RJAA", T0, T0 + timedelta(hours=3))
    tm, clock = _sched_tm([dep], T0 + timedelta(hours=1))
    tm.update(SimState(), 1)
    assert tm.aircraft == []


AIRPORTS = {
    "RCTP": AirportPos("RCTP", 25.0777, 121.233, 106),
    "RJAA": AirportPos("RJAA", 35.76858, 140.388714, 141),
}


def test_parse_airports():
    text = ('"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code","gps_code","local_code","home_link","wikipedia_link","keywords"\n'
            '5528,"RCTP","large_airport","Taoyuan",25.0777,121.233002,106,"AS","TW","TW-TAO","Taoyuan","yes","RCTP","TPE","RCTP",,,,\n'
            '1,"00A","heliport","x",1,1,1,"NA","US","US-PA","x","no",,,,,,,\n')
    a = parse_airports(text)
    assert list(a) == ["RCTP"] and a["RCTP"].elevation_ft == 106


def test_enroute_position_profile():
    f = ScheduledFlight("CAL100", "CAL", "100", "A333", "RCTP", "RJAA", T0, T0 + timedelta(hours=3))
    mid = position_at(f, AIRPORTS["RCTP"], AIRPORTS["RJAA"], T0 + timedelta(minutes=90))
    assert mid[2] == 35000  # 巡航
    early = position_at(f, AIRPORTS["RCTP"], AIRPORTS["RJAA"], T0 + timedelta(minutes=3))
    assert early[2] < mid[2]
    assert position_at(f, AIRPORTS["RCTP"], AIRPORTS["RJAA"], T0 - timedelta(minutes=1)) is None


def test_enroute_spawns_near_player_only():
    f = ScheduledFlight("CAL100", "CAL", "100", "A333", "RCTP", "RJAA", T0, T0 + timedelta(hours=3))
    now = {"t": T0 + timedelta(minutes=90)}
    sim = MockSim()
    er = EnrouteTraffic(sim, ModelLibrary(parse_vmr(VMR)), Schedule([f]), AIRPORTS, clock=lambda: now["t"])
    lat, lon, *_ = position_at(f, AIRPORTS["RCTP"], AIRPORTS["RJAA"], now["t"])
    far = SimState(lat=10, lon=100)
    er.update(far)
    assert er.active == {}
    near = SimState(lat=lat + 0.2, lon=lon, heading_deg=0)
    er.update(near)
    assert len(er.active) == 1 and len(sim.ai) == 1
    assert "CAL100" in er.summary(near) and "6 o'clock" in er.summary(near)
    er.update(far)
    assert er.active == {} and sim.ai == {}
