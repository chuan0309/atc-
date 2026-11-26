"""MSFS 2020/2024 SimConnect 連線（只能在 Windows 上跑）。

用 Python-SimConnect 套件：pip install SimConnect
"""
from __future__ import annotations

import logging
import os
import time

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
        self._pos_def = None
        self._events: dict = {}

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

    # ---------- AI 飛機 ----------
    # 用 AICreateNonATCAircraft 生 FSLTL 模型，凍結 MSFS 自己的 AI 控制，
    # 之後每一步用 SetDataOnSimObject 直接設定位置（跟 BeyondATC / 交通注入器一樣的做法）。
    def _event(self, name: str):
        if name not in self._events:
            self._events[name] = self.sm.map_to_sim_event(name.encode())
        return self._events[name]

    def spawn_ai(self, title, tail, lat, lon, alt_ft, hdg, on_ground, kt):
        from ctypes.wintypes import DWORD
        from SimConnect.Constants import SIMCONNECT_GROUP_PRIORITY_HIGHEST  # type: ignore
        from SimConnect.Enum import SIMCONNECT_DATA_INITPOSITION  # type: ignore

        init = SIMCONNECT_DATA_INITPOSITION(lat, lon, alt_ft, 0.0, 0.0, hdg, 1 if on_ground else 0, int(kt))
        # Python-SimConnect 收到 ASSIGNED_OBJECT_ID 會寫進這個環境變數
        os.environ.pop("SIMCONNECT_OBJECT_ID", None)
        req = self.sm.new_request_id()
        try:
            self.sm.dll.AICreateNonATCAircraft(self.sm.hSimConnect, title.encode(), tail[:12].encode(), init, req.value)
        except Exception as e:  # noqa: BLE001
            log.warning("生 AI 失敗 (%s): %s", title, e)
            return None
        deadline = time.time() + 3
        while time.time() < deadline:
            oid = os.environ.get("SIMCONNECT_OBJECT_ID")
            if oid:
                oid = int(oid)
                for ev in ("FREEZE_LATITUDE_LONGITUDE_SET", "FREEZE_ALTITUDE_SET", "FREEZE_ATTITUDE_SET"):
                    evt = self._event(ev)
                    if evt is not None:
                        self.sm.dll.TransmitClientEvent(self.sm.hSimConnect, oid, evt.value, DWORD(1),
                                                        SIMCONNECT_GROUP_PRIORITY_HIGHEST, DWORD(16))
                log.info("AI %s (%s) object id %d", tail, title, oid)
                return oid
            time.sleep(0.05)
        log.warning("生 AI 沒回應（模型名稱可能不對）: %s", title)
        return None

    def _position_def(self):
        if self._pos_def is None:
            from SimConnect.Constants import SIMCONNECT_UNUSED  # type: ignore
            from SimConnect.Enum import SIMCONNECT_DATATYPE  # type: ignore

            self._pos_def = self.sm.new_def_id()
            for name, unit in (("PLANE LATITUDE", "degrees"), ("PLANE LONGITUDE", "degrees"),
                               ("PLANE ALTITUDE", "feet"), ("PLANE PITCH DEGREES", "degrees"),
                               ("PLANE BANK DEGREES", "degrees"), ("PLANE HEADING DEGREES TRUE", "degrees")):
                self.sm.dll.AddToDataDefinition(self.sm.hSimConnect, self._pos_def.value, name.encode(), unit.encode(),
                                                SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_FLOAT64, 0, SIMCONNECT_UNUSED)
        return self._pos_def

    def move_ai(self, object_id, lat, lon, alt_ft, pitch, bank, hdg):
        from ctypes import c_double, c_void_p, cast, sizeof

        d = self._position_def()
        data = (c_double * 6)(lat, lon, alt_ft, -pitch, bank, hdg)  # MSFS pitch 正值 = 機頭朝下
        try:
            self.sm.dll.SetDataOnSimObject(self.sm.hSimConnect, d.value, object_id, 0, 0, sizeof(data), cast(data, c_void_p))
        except Exception as e:  # noqa: BLE001
            log.debug("移動 AI %s 失敗: %s", object_id, e)

    def remove_ai(self, object_id):
        try:
            self.sm.dll.AIRemoveObject(self.sm.hSimConnect, object_id, self.sm.new_request_id().value)
        except Exception as e:  # noqa: BLE001
            log.debug("移除 AI %s 失敗: %s", object_id, e)

    def close(self) -> None:
        if self.sm:
            self.sm.exit()
