"""MSFS 2020/2024 SimConnect 連線（只能在 Windows 上跑）。

用 Python-SimConnect 套件：pip install SimConnect
"""
from __future__ import annotations

import logging

from .base import SimInterface, SimState

log = logging.getLogger(__name__)

# SimVar 名稱 -> (SimState 欄位, 轉換)
SIMVARS = {
    "PLANE_LATITUDE": ("lat", float),
    "PLANE_LONGITUDE": ("lon", float),
    "PLANE_ALTITUDE": ("altitude_ft", float),
    "PLANE_ALT_ABOVE_GROUND": ("altitude_agl_ft", float),
    "AIRSPEED_INDICATED": ("ias_kt", float),
    "GROUND_VELOCITY": ("ground_speed_kt", float),
    "VERTICAL_SPEED": ("vertical_speed_fpm", lambda v: float(v) * 60.0),  # ft/s -> fpm
    "PLANE_HEADING_DEGREES_MAGNETIC": ("heading_deg", lambda v: float(v) * 57.29578),  # rad -> deg
    "SIM_ON_GROUND": ("on_ground", bool),
    "GENERAL_ENG_COMBUSTION:1": ("engines_running", bool),
    "BRAKE_PARKING_POSITION": ("parking_brake", bool),
    "COM_ACTIVE_FREQUENCY:1": ("com1_active_mhz", float),
    "TRANSPONDER_CODE:1": ("transponder", lambda v: _bcd_to_int(int(v))),
}


def _bcd_to_int(v: int) -> int:
    """舊版 SimConnect 回傳 BCD16，新版直接回十進位，兩種都處理。"""
    if v > 7777:  # 不可能是合法的十進位 squawk，當 BCD 解
        return int(f"{v:x}")
    return v


class MSFSSim(SimInterface):
    def __init__(self):
        self.sm = None
        self.aq = None
        self._lvar_reqs: dict = {}

    def connect(self) -> None:
        from SimConnect import AircraftRequests, SimConnect  # type: ignore

        self.sm = SimConnect()
        self.aq = AircraftRequests(self.sm, _time=200)
        log.info("已連上 MSFS SimConnect")

    def get_state(self) -> SimState:
        st = SimState()
        for var, (fld, conv) in SIMVARS.items():
            try:
                v = self.aq.get(var)
                if v is not None:
                    setattr(st, fld, conv(v))
            except Exception as e:  # noqa: BLE001
                log.debug("讀 %s 失敗: %s", var, e)
        return st

    def _lvar(self, name: str):
        from SimConnect import Request  # type: ignore

        if name not in self._lvar_reqs:
            key = name if name.startswith("L:") else f"L:{name}"
            self._lvar_reqs[name] = Request(
                (key.encode(), b"Number"), self.sm, _time=200, _settable=True
            )
        return self._lvar_reqs[name]

    def get_lvar(self, name: str) -> float | None:
        try:
            return self._lvar(name).value
        except Exception as e:  # noqa: BLE001
            log.debug("讀 L:%s 失敗: %s", name, e)
            return None

    def set_lvar(self, name: str, value: float) -> None:
        try:
            self._lvar(name).value = value
        except Exception as e:  # noqa: BLE001
            log.warning("寫 L:%s 失敗: %s", name, e)

    def close(self) -> None:
        if self.sm:
            self.sm.exit()
