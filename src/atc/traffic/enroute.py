"""你周圍空域的真實班表航班（只顯示，不指揮）。

照班表的起飛/降落時間，算出每架飛機「現在」應該在大圓航線上的哪裡、多高，
離你 radius_nm 以內就生出來，離開就移除。靠近機場的部分交給跑道引擎處理。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..sim.base import SimState
from .airlines import radio_callsign
from .airports import AirportPos
from .fsltl import ModelLibrary
from .geo import bearing_deg, distance_nm, intermediate
from .schedule import Schedule, ScheduledFlight

log = logging.getLogger(__name__)

AIRPORT_EXCLUSION_NM = 12.0


@dataclass
class EnrouteAircraft:
    flight: ScheduledFlight
    title: str
    lat: float = 0.0
    lon: float = 0.0
    alt_ft: float = 0.0
    hdg: float = 0.0
    object_id: int | None = None


def cruise_altitude(dist_nm: float) -> float:
    return 37000 if dist_nm > 1500 else 35000 if dist_nm > 600 else 28000 if dist_nm > 250 else 20000


def position_at(f: ScheduledFlight, a: AirportPos, b: AirportPos, now: datetime):
    """回傳 (lat, lon, alt_ft, hdg, 離起飛機場 nm, 離降落機場 nm)；不在空中回 None。"""
    if not (f.dep_utc and f.arr_utc) or not (f.dep_utc <= now <= f.arr_utc):
        return None
    total = (f.arr_utc - f.dep_utc).total_seconds()
    frac = (now - f.dep_utc).total_seconds() / total if total > 0 else 0
    D = distance_nm(a.lat, a.lon, b.lat, b.lon)
    lat, lon = intermediate(a.lat, a.lon, b.lat, b.lon, frac)
    s = frac * D
    alt = min(cruise_altitude(D), a.elevation_ft + s * 330, b.elevation_ft + (D - s) * 318)
    hdg = bearing_deg(lat, lon, b.lat, b.lon)
    return lat, lon, alt, hdg, s, D - s


class EnrouteTraffic:
    def __init__(self, sim, library: ModelLibrary, schedule: Schedule, airports: dict[str, AirportPos],
                 radius_nm: float = 40.0, max_aircraft: int = 15,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.sim = sim
        self.lib = library
        self.schedule = schedule
        self.airports = airports
        self.radius = radius_nm
        self.max = max_aircraft
        self.clock = clock
        self.active: dict[str, EnrouteAircraft] = {}

    def _candidates(self, p: SimState, now: datetime):
        out = []
        for f in self.schedule.airborne(now):
            a, b = self.airports.get(f.origin), self.airports.get(f.destination)
            if not a or not b:
                continue
            pos = position_at(f, a, b, now)
            if not pos:
                continue
            lat, lon, alt, hdg, from_dep, to_arr = pos
            if from_dep < AIRPORT_EXCLUSION_NM or to_arr < AIRPORT_EXCLUSION_NM:
                continue
            d = distance_nm(p.lat, p.lon, lat, lon)
            if d <= self.radius:
                out.append((d, f, pos))
        out.sort(key=lambda x: x[0])
        return out[: self.max]

    def update(self, p: SimState, dt: float = 0) -> None:
        now = self.clock()
        wanted = {}
        for _, f, (lat, lon, alt, hdg, _, _) in self._candidates(p, now):
            wanted[f.key] = (f, lat, lon, alt, hdg)
        for key in list(self.active):
            if key not in wanted:
                self._remove(key)
        for key, (f, lat, lon, alt, hdg) in wanted.items():
            ac = self.active.get(key)
            if ac is None:
                m = self.lib.match(f.airline, f.type_code) if len(self.lib) else None
                ac = EnrouteAircraft(f, m.title if m else "")
                if ac.title:
                    ac.object_id = self.sim.spawn_ai(ac.title, f.callsign, lat, lon, alt, hdg, False, 450)
                self.active[key] = ac
            ac.lat, ac.lon, ac.alt_ft, ac.hdg = lat, lon, alt, hdg
            if ac.object_id is not None:
                self.sim.move_ai(ac.object_id, lat, lon, alt, 0.0, 0.0, hdg)

    def _remove(self, key: str) -> None:
        ac = self.active.pop(key)
        if ac.object_id is not None:
            self.sim.remove_ai(ac.object_id)

    def clear(self) -> None:
        for key in list(self.active):
            self._remove(key)

    def summary(self, p: SimState) -> str:
        if not self.active:
            return ""
        lines = ["Nearby en-route traffic (real schedule, not under your control):"]
        for ac in sorted(self.active.values(), key=lambda a: distance_nm(p.lat, p.lon, a.lat, a.lon)):
            d = distance_nm(p.lat, p.lon, ac.lat, ac.lon)
            brg = bearing_deg(p.lat, p.lon, ac.lat, ac.lon)
            rel = ((brg - p.heading_deg) + 360) % 360
            clock = round(rel / 30) % 12 or 12
            f = ac.flight
            lines.append(f"- {f.callsign} ({radio_callsign(f.airline, f.number)}) {f.type_code or '?'} "
                         f"{f.origin}->{f.destination}, {d:.0f}nm at your {clock} o'clock, "
                         f"{ac.alt_ft:.0f}ft, track {ac.hdg:03.0f}")
        return "\n".join(lines)
