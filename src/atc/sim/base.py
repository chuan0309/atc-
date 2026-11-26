from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SimState:
    lat: float = 0.0
    lon: float = 0.0
    altitude_ft: float = 0.0        # MSL
    altitude_agl_ft: float = 0.0
    ias_kt: float = 0.0
    ground_speed_kt: float = 0.0
    vertical_speed_fpm: float = 0.0
    heading_deg: float = 0.0
    on_ground: bool = True
    engines_running: bool = False
    parking_brake: bool = True
    com1_active_mhz: float = 0.0
    transponder: int = 1200

    def brief(self) -> str:
        return (
            f"alt {self.altitude_ft:.0f}ft MSL ({self.altitude_agl_ft:.0f} AGL), "
            f"IAS {self.ias_kt:.0f}kt, GS {self.ground_speed_kt:.0f}kt, "
            f"VS {self.vertical_speed_fpm:+.0f}fpm, hdg {self.heading_deg:03.0f}, "
            f"{'on ground' if self.on_ground else 'airborne'}, "
            f"engines {'running' if self.engines_running else 'off'}, "
            f"parking brake {'set' if self.parking_brake else 'released'}, "
            f"COM1 {self.com1_active_mhz:.3f}, squawk {self.transponder:04d}"
        )


class SimInterface(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def get_state(self) -> SimState: ...

    @abstractmethod
    def get_lvar(self, name: str) -> float | None:
        """讀 L:var（GSX 用這個溝通）。"""

    @abstractmethod
    def set_lvar(self, name: str, value: float) -> None: ...

    # ---- AI 飛機（FSLTL 模型）。不支援的 backend 回傳 None，交通照樣「虛擬」運作 ----
    def spawn_ai(self, title: str, tail: str, lat: float, lon: float, alt_ft: float,
                 hdg: float, on_ground: bool, kt: float) -> int | None:
        return None

    def move_ai(self, object_id: int, lat: float, lon: float, alt_ft: float,
                pitch: float, bank: float, hdg: float) -> None:
        pass

    def remove_ai(self, object_id: int) -> None:
        pass

    def close(self) -> None:
        pass
