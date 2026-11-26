"""假的模擬器：沒開 MSFS 也能測整個流程。

用 advance() 一步步推進飛行階段，或直接改 state。
"""
from __future__ import annotations

from .base import SimInterface, SimState

# 一趟典型航班的簡化腳本：(說明, 要套用的欄位)
SCRIPT = [
    ("cold & dark at gate", dict()),
    ("engines start", dict(engines_running=True)),
    ("pushback / taxi", dict(parking_brake=False, ground_speed_kt=15)),
    ("lined up, takeoff roll", dict(ground_speed_kt=140, ias_kt=140)),
    ("airborne climbing", dict(on_ground=False, altitude_ft=3000, altitude_agl_ft=2900, ias_kt=220, vertical_speed_fpm=2500)),
    ("passing FL150", dict(altitude_ft=15000, altitude_agl_ft=14900, ias_kt=300, vertical_speed_fpm=2000)),
    ("cruise", dict(altitude_ft=36000, altitude_agl_ft=35900, ias_kt=270, vertical_speed_fpm=0)),
    ("descending", dict(altitude_ft=24000, altitude_agl_ft=23900, vertical_speed_fpm=-2200)),
    ("approach", dict(altitude_ft=6000, altitude_agl_ft=5900, ias_kt=210, vertical_speed_fpm=-1200)),
    ("final", dict(altitude_ft=1500, altitude_agl_ft=1400, ias_kt=145, vertical_speed_fpm=-750)),
    ("landed, rollout", dict(on_ground=True, altitude_ft=100, altitude_agl_ft=0, ias_kt=60, ground_speed_kt=60, vertical_speed_fpm=0)),
    ("taxi in", dict(ias_kt=0, ground_speed_kt=15)),
    ("parked", dict(ground_speed_kt=0, parking_brake=True, engines_running=False)),
]


class MockSim(SimInterface):
    def __init__(self, **_):
        self.state = SimState(com1_active_mhz=121.800)
        self.lvars: dict[str, float] = {}
        self.step = 0
        self.ai: dict[int, dict] = {}
        self._next_id = 1000

    def connect(self) -> None:
        pass

    def get_state(self) -> SimState:
        return self.state

    def get_lvar(self, name: str) -> float | None:
        return self.lvars.get(name)

    def set_lvar(self, name: str, value: float) -> None:
        self.lvars[name] = value

    def advance(self) -> str:
        if self.step < len(SCRIPT) - 1:
            self.step += 1
        label, changes = SCRIPT[self.step]
        for k, v in changes.items():
            setattr(self.state, k, v)
        return label

    def spawn_ai(self, title, tail, lat, lon, alt_ft, hdg, on_ground, kt):
        self._next_id += 1
        self.ai[self._next_id] = dict(title=title, tail=tail, lat=lat, lon=lon, alt=alt_ft, hdg=hdg)
        return self._next_id

    def move_ai(self, object_id, lat, lon, alt_ft, pitch, bank, hdg):
        self.ai[object_id].update(lat=lat, lon=lon, alt=alt_ft, hdg=hdg)

    def remove_ai(self, object_id):
        self.ai.pop(object_id, None)
