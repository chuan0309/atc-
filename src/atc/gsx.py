"""GSX Pro 整合。

GSX 透過 L:var 跟外部程式溝通：
- FSDT_GSX_*_STATE：各項地勤服務狀態
- FSDT_GSX_MENU_OPEN = 1 打開 GSX 選單
- FSDT_GSX_MENU_CHOICE = n 選第 n 個選項（從 0 開始）
選單文字 GSX 會寫到一個 "menu" 檔，我們讀它來找「Request Pushback」在第幾個。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from .sim.base import SimInterface

log = logging.getLogger(__name__)


class GSXState(IntEnum):
    UNKNOWN = 0
    AVAILABLE = 1
    NOT_AVAILABLE = 2
    BYPASSED = 3
    REQUESTED = 4
    PERFORMING = 5
    COMPLETED = 6


SERVICES = {
    "deboarding": "FSDT_GSX_DEBOARDING_STATE",
    "catering": "FSDT_GSX_CATERING_STATE",
    "refueling": "FSDT_GSX_REFUELING_STATE",
    "boarding": "FSDT_GSX_BOARDING_STATE",
    "pushback": "FSDT_GSX_DEPARTURE_STATE",
    "deicing": "FSDT_GSX_DEICING_STATE",
}

MENU_OPEN = "FSDT_GSX_MENU_OPEN"
MENU_CHOICE = "FSDT_GSX_MENU_CHOICE"
# GSX 預設主選單裡 Request Pushback 通常是第 5 個（index 4），找不到選單檔時用這個
DEFAULT_PUSHBACK_INDEX = 4


def _candidate_menu_files() -> list[Path]:
    """GSX Pro 選單檔可能的位置（不同版本/安裝方式會不一樣）。"""
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "Virtuali" / "GSX" / "MSFS" / "menu")
    for base in (os.environ.get("MSFS_COMMUNITY"), os.environ.get("MSFS_PACKAGES")):
        if base:
            out.append(Path(base) / "fsdreamteam-gsx-pro" / "html_ui" / "InGamePanels" / "FSDT_GSX_Panel" / "menu")
    return out


@dataclass
class GSXEvent:
    service: str
    old: GSXState
    new: GSXState

    def describe(self) -> str:
        return f"GSX {self.service}: {self.old.name.lower()} -> {self.new.name.lower()}"


class GSX:
    def __init__(self, sim: SimInterface, menu_file: str = ""):
        self.sim = sim
        self.menu_file = Path(menu_file) if menu_file else None
        self.states: dict[str, GSXState] = {k: GSXState.UNKNOWN for k in SERVICES}

    def _find_menu_file(self) -> Path | None:
        if self.menu_file and self.menu_file.exists():
            return self.menu_file
        for p in _candidate_menu_files():
            if p.exists():
                return p
        return None

    def read_states(self) -> dict[str, GSXState]:
        for svc, var in SERVICES.items():
            v = self.sim.get_lvar(var)
            try:
                self.states[svc] = GSXState(int(v)) if v is not None else GSXState.UNKNOWN
            except ValueError:
                self.states[svc] = GSXState.UNKNOWN
        return dict(self.states)

    def poll(self) -> list[GSXEvent]:
        """讀狀態並回傳有變化的服務。"""
        old = dict(self.states)
        new = self.read_states()
        return [GSXEvent(s, old[s], new[s]) for s in SERVICES if old[s] != new[s]]

    def read_menu(self) -> list[str]:
        p = self._find_menu_file()
        if not p:
            return []
        try:
            lines = [l.strip() for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()]
            return [l for l in lines[1:] if l]  # 第一行是標題
        except OSError:
            return []

    def open_menu(self) -> None:
        self.sim.set_lvar(MENU_OPEN, 1)

    def choose(self, index: int) -> None:
        self.sim.set_lvar(MENU_CHOICE, index)

    def select_by_text(self, keyword: str, fallback_index: int | None = None, wait: float = 1.0) -> bool:
        self.open_menu()
        time.sleep(wait)
        items = self.read_menu()
        for i, text in enumerate(items):
            if keyword.lower() in text.lower():
                log.info("GSX 選單選擇 [%d] %s", i, text)
                self.choose(i)
                return True
        if fallback_index is not None:
            log.info("找不到 GSX 選單檔/選項，用預設位置 %d", fallback_index)
            self.choose(fallback_index)
            return True
        return False

    def request_pushback(self) -> bool:
        if self.states.get("pushback") in (GSXState.REQUESTED, GSXState.PERFORMING, GSXState.COMPLETED):
            return False
        return self.select_by_text("pushback", DEFAULT_PUSHBACK_INDEX)

    def status_text(self) -> str:
        return ", ".join(f"{k}={v.name.lower()}" for k, v in self.states.items() if v != GSXState.UNKNOWN) or "unknown"
