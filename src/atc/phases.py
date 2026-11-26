"""飛行階段判斷 + 現在該跟哪個管制席位講話。"""
from __future__ import annotations

from enum import Enum

from .sim.base import SimState


class Phase(str, Enum):
    PREFLIGHT = "preflight"      # 在登機門，要 IFR clearance
    PUSHBACK = "pushback"        # 申請推出/開車
    TAXI_OUT = "taxi_out"
    TAKEOFF = "takeoff"          # 跑道上/準備起飛
    DEPARTURE = "departure"      # 起飛後爬升
    CRUISE = "cruise"
    DESCENT = "descent"
    APPROACH = "approach"
    LANDING = "landing"          # 最後進場/落地滾行
    TAXI_IN = "taxi_in"
    PARKED = "parked"


# 每個階段預設的管制席位
CONTROLLER = {
    Phase.PREFLIGHT: "delivery",
    Phase.PUSHBACK: "ground",
    Phase.TAXI_OUT: "ground",
    Phase.TAKEOFF: "tower",
    Phase.DEPARTURE: "departure",
    Phase.CRUISE: "center",
    Phase.DESCENT: "center",
    Phase.APPROACH: "approach",
    Phase.LANDING: "tower",
    Phase.TAXI_IN: "ground",
    Phase.PARKED: "ground",
}

ORDER = list(Phase)


class PhaseTracker:
    """依照模擬器數據推算飛行階段。只往前走，不會倒退（避免抖動）。

    ATC 腦袋（Gemini）也可以用 force() 推進，例如 delivery 給完 clearance -> pushback。
    """

    def __init__(self, cruise_alt_ft: int, dest_elev_ft: int = 0):
        self.phase = Phase.PREFLIGHT
        self.cruise_alt = cruise_alt_ft or 30000
        self.dest_elev = dest_elev_ft
        self.max_alt = 0.0

    def force(self, phase: Phase) -> bool:
        if ORDER.index(phase) > ORDER.index(self.phase):
            self.phase = phase
            return True
        return False

    def _guess(self, s: SimState) -> Phase:
        p = self.phase
        self.max_alt = max(self.max_alt, s.altitude_ft)
        if s.on_ground:
            if p in (Phase.PREFLIGHT, Phase.PUSHBACK) and not s.parking_brake and s.ground_speed_kt > 3:
                return Phase.TAXI_OUT
            if p == Phase.TAXI_OUT and s.ground_speed_kt > 40:
                return Phase.TAKEOFF
            if p in (Phase.APPROACH, Phase.DESCENT, Phase.LANDING) and s.ground_speed_kt < 35:
                return Phase.TAXI_IN
            if p == Phase.TAXI_IN and s.ground_speed_kt < 1 and s.parking_brake and not s.engines_running:
                return Phase.PARKED
            return p
        # 空中
        if p in (Phase.PREFLIGHT, Phase.PUSHBACK, Phase.TAXI_OUT, Phase.TAKEOFF):
            return Phase.DEPARTURE
        if p == Phase.DEPARTURE and (s.altitude_ft > min(18000, self.cruise_alt - 2000)):
            return Phase.CRUISE
        if p == Phase.CRUISE and s.vertical_speed_fpm < -800 and s.altitude_ft < self.max_alt - 3000:
            return Phase.DESCENT
        if p in (Phase.CRUISE, Phase.DESCENT) and s.altitude_ft - self.dest_elev < 10000 and s.vertical_speed_fpm < 0:
            return Phase.APPROACH
        if p == Phase.APPROACH and s.altitude_agl_ft < 2000 and s.vertical_speed_fpm < 0:
            return Phase.LANDING
        return p

    def update(self, s: SimState) -> Phase | None:
        """回傳新階段（有變的話），沒變回 None。"""
        new = self._guess(s)
        if new != self.phase and self.force(new):
            return new
        return None

    @property
    def controller(self) -> str:
        return CONTROLLER[self.phase]
