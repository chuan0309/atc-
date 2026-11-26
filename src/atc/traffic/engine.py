"""AI 交通引擎：生 AI 飛機、讓它們起飛降落、管跑道、產生無線電對話。

運作方式（簡化版 BeyondATC）：
- 出發機：生在跑道頭旁邊等待 -> 塔台給 line up -> 起飛滾行 -> 爬升 -> 交給 departure -> 消失
- 到場機：生在 10 海里五邊 -> 塔台許可落地 -> 落地滾行 -> 脫離跑道交給 ground -> 消失
- 跑道同時只給一架用（包含你）。你在五邊或你已拿到許可，AI 會讓你。
- 有其他飛機擋跑道，到場機 1 海里時會被叫重飛。
"""
from __future__ import annotations

import itertools
import logging
import random
from dataclasses import dataclass, field
from enum import Enum

from ..sim.base import SimInterface, SimState
from .airlines import radio_callsign
from .fsltl import Model, ModelLibrary
from .geo import along_cross_nm, destination
from .runways import Runway
from .speech import say_callsign, say_runway

log = logging.getLogger(__name__)

GLIDE_FT_PER_NM = 318.0  # 3 度下滑道


class AIState(str, Enum):
    HOLDING_SHORT = "holding short"
    LINEUP = "lined up"
    TAKEOFF_ROLL = "takeoff roll"
    CLIMB = "climbing out"
    FINAL = "on final"
    ROLLOUT = "landing rollout"
    GO_AROUND = "going around"
    DONE = "done"


@dataclass
class RadioCall:
    speaker: str        # "atc" 或 "pilot"
    controller: str     # tower / ground / departure
    text: str
    callsign: str = ""


@dataclass
class AIAircraft:
    callsign: str
    radio: str
    type_code: str
    title: str
    arrival: bool
    state: AIState
    lat: float
    lon: float
    alt_ft: float
    hdg: float
    speed_kt: float = 0.0
    pitch: float = 0.0
    object_id: int | None = None
    timer: float = 0.0
    cleared: bool = False
    handed_off: bool = False

    @property
    def spoken(self) -> str:
        return say_callsign(self.radio)


@dataclass
class TrafficSettings:
    departures_per_hour: float = 20
    arrivals_per_hour: float = 20
    max_holding: int = 2
    max_arrivals: int = 2
    spawn_final_nm: float = 10.0
    min_arrival_spacing_nm: float = 4.0
    departure_interval_s: float = 90.0
    radio_chatter: bool = True
    prefer_types: tuple[str, ...] = ("A320", "A321", "B738", "A333", "B77W", "A359", "B789", "A20N", "A21N", "B38M")


class TrafficManager:
    def __init__(self, sim: SimInterface, library: ModelLibrary, settings: TrafficSettings | None = None,
                 rng: random.Random | None = None):
        self.sim = sim
        self.lib = library
        self.s = settings or TrafficSettings()
        self.rng = rng or random.Random()
        self.runway: Runway | None = None
        self.aircraft: list[AIAircraft] = []
        self.radio: list[RadioCall] = []
        self.player_reservation: str | None = None   # "takeoff" / "landing"
        self._since_departure = 1e9
        self._numbers = itertools.count(self.rng.randint(100, 800))

    # ---------- 設定 ----------
    def set_runway(self, rwy: Runway | None) -> None:
        if rwy is self.runway or (rwy and self.runway and rwy.airport == self.runway.airport and rwy.ident == self.runway.ident):
            return
        self.clear()
        self.runway = rwy
        if rwy:
            log.info("AI 交通：%s 跑道 %s", rwy.airport, rwy.ident)

    def clear(self) -> None:
        for a in self.aircraft:
            self._despawn(a)
        self.aircraft = []

    # ---------- 生飛機 ----------
    def _new_identity(self) -> tuple[str, str, Model | None]:
        m = self.lib.random_airline_model(self.s.prefer_types) if len(self.lib) else None
        airline = m.airline if m else self.rng.choice(["CAL", "EVA", "TTW", "SJX", "CPA", "JAL", "ANA", "KAL"])
        num = str(next(self._numbers))
        return f"{airline}{num}", radio_callsign(airline, num), m

    def _spawn_sim(self, a: AIAircraft, on_ground: bool) -> None:
        if a.title:
            a.object_id = self.sim.spawn_ai(a.title, a.callsign, a.lat, a.lon, a.alt_ft, a.hdg, on_ground, a.speed_kt)

    def _despawn(self, a: AIAircraft) -> None:
        if a.object_id is not None:
            self.sim.remove_ai(a.object_id)
            a.object_id = None

    def spawn_departure(self) -> AIAircraft | None:
        r = self.runway
        if not r:
            return None
        cs, radio, m = self._new_identity()
        n_holding = sum(1 for a in self.aircraft if a.state == AIState.HOLDING_SHORT)
        # 停在跑道頭右邊約 120 米，排隊的往後排
        base = destination(r.lat, r.lon, r.heading_true, 0.03 + 0.05 * n_holding)
        lat, lon = destination(*base, (r.heading_true + 90) % 360, 0.065)
        a = AIAircraft(cs, radio, m.type_code if m else "A320", m.title if m else "", False,
                       AIState.HOLDING_SHORT, lat, lon, r.elevation_ft, (r.heading_true - 90) % 360)
        self._spawn_sim(a, True)
        self.aircraft.append(a)
        self._say("pilot", "tower", f"Tower, {a.spoken}, holding short runway {say_runway(r.ident)}, ready for departure.", a)
        return a

    def spawn_arrival(self, dist_nm: float | None = None) -> AIAircraft | None:
        r = self.runway
        if not r:
            return None
        d = dist_nm or self.s.spawn_final_nm
        cs, radio, m = self._new_identity()
        lat, lon = destination(r.lat, r.lon, (r.heading_true + 180) % 360, d)
        a = AIAircraft(cs, radio, m.type_code if m else "A320", m.title if m else "", True,
                       AIState.FINAL, lat, lon, r.elevation_ft + d * GLIDE_FT_PER_NM + 50, r.heading_true,
                       speed_kt=150, pitch=2.5)
        self._spawn_sim(a, False)
        self.aircraft.append(a)
        number = sum(1 for x in self.aircraft if x.arrival and x.state == AIState.FINAL)
        self._say("pilot", "tower", f"Tower, {a.spoken}, {round(d)} mile final runway {say_runway(r.ident)}.", a)
        self._say("atc", "tower", f"{a.spoken}, Tower, continue approach, number {number}.", a)
        return a

    # ---------- 狀態判斷 ----------
    def _rel(self, lat, lon) -> tuple[float, float]:
        """相對跑道頭：(沿跑道距離, 偏離中心線)，海里。五邊上的飛機沿線距離是負的。"""
        return along_cross_nm(lat, lon, self.runway.lat, self.runway.lon, self.runway.heading_true)

    def player_on_runway(self, p: SimState) -> bool:
        if not self.runway or not p.on_ground:
            return False
        along, cross = self._rel(p.lat, p.lon)
        return abs(cross) < 0.03 and -0.05 < along < self.runway.length_nm + 0.05

    def player_final_nm(self, p: SimState) -> float | None:
        """你在五邊的話回傳距離跑道頭幾海里，不在五邊回 None。"""
        if not self.runway or p.on_ground:
            return None
        along, cross = self._rel(p.lat, p.lon)
        if -12 < along < 0.3 and abs(cross) < 1.2 and p.altitude_agl_ft < 4500:
            return max(0.0, -along)
        return None

    def runway_occupant(self, p: SimState, exclude: AIAircraft | None = None) -> str | None:
        if self.player_on_runway(p):
            return "player"
        for a in self.aircraft:
            if a is exclude:
                continue
            if a.state in (AIState.LINEUP, AIState.TAKEOFF_ROLL, AIState.ROLLOUT):
                return a.callsign
            if a.state == AIState.CLIMB and a.alt_ft - self.runway.elevation_ft < 300:
                return a.callsign
        return None

    def _arrival_dist(self, a: AIAircraft) -> float:
        return -self._rel(a.lat, a.lon)[0]

    # ---------- 每一步 ----------
    def update(self, p: SimState, dt: float) -> None:
        if not self.runway:
            return
        self._since_departure += dt
        if p.altitude_agl_ft > 50 and self.player_reservation == "takeoff":
            self.player_reservation = None
        if p.on_ground and p.ground_speed_kt < 40 and self.player_reservation == "landing" and not self.player_on_runway(p):
            self.player_reservation = None
        self._maybe_spawn(p, dt)
        for a in list(self.aircraft):
            self._step(a, p, dt)
            if a.state == AIState.DONE:
                self._despawn(a)
                self.aircraft.remove(a)
            elif a.object_id is not None:
                self.sim.move_ai(a.object_id, a.lat, a.lon, a.alt_ft, a.pitch, 0.0, a.hdg)

    def _maybe_spawn(self, p: SimState, dt: float) -> None:
        s = self.s
        holding = sum(1 for a in self.aircraft if a.state == AIState.HOLDING_SHORT)
        if holding < s.max_holding and self.rng.random() < s.departures_per_hour / 3600 * dt:
            self.spawn_departure()
        arrivals = [a for a in self.aircraft if a.arrival and a.state == AIState.FINAL]
        if len(arrivals) < s.max_arrivals and self.rng.random() < s.arrivals_per_hour / 3600 * dt:
            others = [self._arrival_dist(a) for a in arrivals]
            pf = self.player_final_nm(p)
            if pf is not None:
                others.append(pf)
            if all(abs(s.spawn_final_nm - d) >= s.min_arrival_spacing_nm for d in others):
                self.spawn_arrival()

    def _can_depart(self, a: AIAircraft, p: SimState) -> bool:
        if self.player_reservation or self.runway_occupant(p, exclude=a):
            return False
        if self._since_departure < self.s.departure_interval_s:
            return False
        pf = self.player_final_nm(p)
        if pf is not None and pf < 6:
            return False
        if any(x.arrival and x.state == AIState.FINAL and self._arrival_dist(x) < 4 for x in self.aircraft):
            return False
        first = next(x for x in self.aircraft if x.state == AIState.HOLDING_SHORT)
        return first is a

    def _move(self, a: AIAircraft, dt: float) -> None:
        a.lat, a.lon = destination(a.lat, a.lon, a.hdg, a.speed_kt * dt / 3600)

    def _step(self, a: AIAircraft, p: SimState, dt: float) -> None:
        r = self.runway
        rw = say_runway(r.ident)
        if a.state == AIState.HOLDING_SHORT:
            if self._can_depart(a, p):
                a.state, a.timer = AIState.LINEUP, 0.0
                a.lat, a.lon, a.hdg = r.lat, r.lon, r.heading_true
                self._since_departure = 0.0
                self._say("atc", "tower", f"{a.spoken}, runway {rw}, line up and wait.", a)
                self._say("pilot", "tower", f"Line up and wait runway {rw}, {a.spoken}.", a)
        elif a.state == AIState.LINEUP:
            a.timer += dt
            if a.timer > 20:
                a.state = AIState.TAKEOFF_ROLL
                self._say("atc", "tower", f"{a.spoken}, runway {rw}, cleared for takeoff.", a)
                self._say("pilot", "tower", f"Cleared for takeoff runway {rw}, {a.spoken}.", a)
        elif a.state == AIState.TAKEOFF_ROLL:
            a.speed_kt = min(155.0, a.speed_kt + 3.0 * dt)
            self._move(a, dt)
            if a.speed_kt >= 155:
                a.state, a.pitch = AIState.CLIMB, 10.0
        elif a.state == AIState.CLIMB:
            a.speed_kt = min(220.0, a.speed_kt + 1.5 * dt)
            a.alt_ft += 2500 * dt / 60
            self._move(a, dt)
            along, _ = self._rel(a.lat, a.lon)
            if along > r.length_nm + 2 and not a.handed_off:
                a.handed_off = True
                self._say("atc", "tower", f"{a.spoken}, contact departure, good day.", a)
                self._say("pilot", "tower", f"Departure, {a.spoken}, good day.", a)
            if along > 10:
                a.state = AIState.DONE
        elif a.state == AIState.FINAL:
            self._move(a, dt)
            d = self._arrival_dist(a)
            a.alt_ft = r.elevation_ft + max(0.0, d) * GLIDE_FT_PER_NM + 50 * min(1.0, max(d, 0))
            blocked = self.runway_occupant(p, exclude=a) or self.player_reservation
            if not a.cleared and d < 6 and not blocked:
                a.cleared = True
                self._say("atc", "tower", f"{a.spoken}, runway {rw}, cleared to land.", a)
                self._say("pilot", "tower", f"Cleared to land runway {rw}, {a.spoken}.", a)
            if d < 1.0 and blocked:
                a.state, a.pitch = AIState.GO_AROUND, 8.0
                self._say("atc", "tower", f"{a.spoken}, go around, I say again, go around, runway occupied.", a)
                self._say("pilot", "tower", f"Going around, {a.spoken}.", a)
            elif d <= 0:
                a.state, a.pitch, a.alt_ft = AIState.ROLLOUT, 0.0, r.elevation_ft
        elif a.state == AIState.ROLLOUT:
            a.speed_kt = max(20.0, a.speed_kt - 4.0 * dt)
            self._move(a, dt)
            if a.speed_kt <= 20:
                a.state = AIState.DONE
                self._say("atc", "tower", f"{a.spoken}, vacate when able, contact ground, good day.", a)
                self._say("pilot", "tower", f"Contact ground, {a.spoken}.", a)
        elif a.state == AIState.GO_AROUND:
            a.speed_kt = min(190.0, a.speed_kt + 2 * dt)
            a.alt_ft += 2000 * dt / 60
            self._move(a, dt)
            if self._rel(a.lat, a.lon)[0] > r.length_nm + 5:
                a.state = AIState.DONE

    def _say(self, speaker: str, controller: str, text: str, a: AIAircraft) -> None:
        log.debug("[%s] %s", speaker, text)
        if self.s.radio_chatter:
            self.radio.append(RadioCall(speaker, controller, text, a.callsign))

    def pop_radio(self) -> list[RadioCall]:
        out, self.radio = self.radio, []
        return out

    # ---------- 給 Gemini 看的交通狀況 ----------
    def summary(self, p: SimState) -> str:
        if not self.runway:
            return "no AI traffic"
        occ = self.runway_occupant(p)
        lines = [f"Active runway {self.runway.airport} {self.runway.ident}: "
                 + (f"OCCUPIED by {occ}" if occ and occ != "player" else "occupied by you (player)" if occ else "clear")]
        if self.player_reservation:
            lines.append(f"Player already holds a {self.player_reservation} clearance.")
        for a in self.aircraft:
            extra = ""
            if a.arrival and a.state == AIState.FINAL:
                extra = f" {self._arrival_dist(a):.1f}nm final" + (", cleared to land" if a.cleared else "")
            lines.append(f"- {a.callsign} ({a.radio}) {a.type_code} {'arrival' if a.arrival else 'departure'}: {a.state.value}{extra}")
        return "\n".join(lines)
