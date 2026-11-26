"""找 FSLTL 的飛機模型。

兩種來源（有哪個用哪個）：
1. FSLTL 附的模型對照表 FSLTL_Rules.vmr（XML，vPilot 格式）：航空公司 + 機型 -> 模型名稱
2. 直接掃 Community 資料夾裡 fsltl 開頭套件的 aircraft.cfg，讀 title / icao_airline / 機型

SimConnect 生 AI 飛機時要的就是 aircraft.cfg 裡的 title。
"""
from __future__ import annotations

import configparser
import logging
import os
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Model:
    title: str
    type_code: str      # ICAO 機型，例如 A320
    airline: str = ""   # ICAO 航空公司，例如 CAL；空字串 = 通用塗裝


def find_community_folders() -> list[Path]:
    """從 UserCfg.opt 找 MSFS 2020/2024 的 Community 資料夾（Steam 跟 MS Store 版都找）。"""
    roots = []
    local, roaming = os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")
    if local:
        for pkg in ("Microsoft.FlightSimulator_8wekyb3d8bbwe", "Microsoft.Limitless_8wekyb3d8bbwe"):
            roots.append(Path(local) / "Packages" / pkg / "LocalCache" / "UserCfg.opt")
    if roaming:
        for name in ("Microsoft Flight Simulator", "Microsoft Flight Simulator 2024"):
            roots.append(Path(roaming) / name / "UserCfg.opt")
    out = []
    for cfg in roots:
        if not cfg.exists():
            continue
        m = re.search(r'InstalledPackagesPath\s+"([^"]+)"', cfg.read_text(errors="ignore"))
        if m:
            p = Path(m.group(1)) / "Community"
            if p.exists():
                out.append(p)
    return out


def parse_vmr(text: str) -> list[Model]:
    out = []
    root = ET.fromstring(text)
    for rule in root.iter("ModelMatchRule"):
        type_code = rule.get("TypeCode", "").upper()
        airline = rule.get("CallsignPrefix", "").upper()
        for name in rule.get("ModelName", "").split("//"):
            if name.strip() and type_code:
                out.append(Model(name.strip(), type_code, airline))
    return out


def parse_aircraft_cfg(text: str) -> list[Model]:
    cp = configparser.ConfigParser(strict=False, interpolation=None, inline_comment_prefixes=(";", "//"))
    try:
        cp.read_string(text)
    except configparser.Error:
        return []
    general_type = ""
    for sec in cp.sections():
        if sec.lower() == "general":
            general_type = cp[sec].get("icao_type_designator", "").strip('" ').upper()
    out = []
    for sec in cp.sections():
        if not sec.lower().startswith("fltsim."):
            continue
        s = cp[sec]
        title = s.get("title", "").strip('" ')
        if not title:
            continue
        t = s.get("icao_type_designator", general_type).strip('" ').upper()
        airline = s.get("icao_airline", "").strip('" ').upper()
        if not t:  # FSLTL 資料夾名稱通常像 FSLTL_A320_xxx，用來猜機型
            m = re.search(r"FSLTL[ _-]([A-Z0-9]{3,4})", title.upper())
            t = m.group(1) if m else ""
        if t:
            out.append(Model(title, t, airline))
    return out


class ModelLibrary:
    def __init__(self, models: list[Model]):
        self.models = models
        self._by_key: dict[tuple[str, str], list[Model]] = {}
        for m in models:
            self._by_key.setdefault((m.airline, m.type_code), []).append(m)

    @classmethod
    def load(cls, community: str | Path | None = None, vmr: str | Path | None = None) -> "ModelLibrary":
        models: list[Model] = []
        folders = [Path(community)] if community else find_community_folders()
        vmr_files = [Path(vmr)] if vmr else []
        for f in folders:
            for pkg in f.glob("fsltl*"):
                vmr_files += list(pkg.glob("*.vmr"))
        for v in vmr_files:
            try:
                models += parse_vmr(v.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, ET.ParseError) as e:
                log.warning("讀 %s 失敗: %s", v, e)
        if not models:  # 沒有 vmr 就掃 aircraft.cfg
            for f in folders:
                for pkg in f.glob("fsltl*"):
                    for cfg in pkg.glob("SimObjects/Airplanes/*/aircraft.cfg"):
                        models += parse_aircraft_cfg(cfg.read_text(encoding="utf-8", errors="ignore"))
        log.info("FSLTL 模型: 共 %d 個", len(models))
        return cls(models)

    def __len__(self) -> int:
        return len(self.models)

    def match(self, airline: str, type_code: str) -> Model | None:
        """先找該航空公司塗裝，沒有就用同機型的通用塗裝，再沒有就任何同機型。"""
        airline, type_code = airline.upper(), type_code.upper()
        for key in ((airline, type_code), ("", type_code)):
            if key in self._by_key:
                return random.choice(self._by_key[key])
        same_type = [m for m in self.models if m.type_code == type_code]
        return random.choice(same_type) if same_type else None

    def random_airline_model(self, prefer_types: tuple[str, ...] = ()) -> Model | None:
        """隨機挑一個有航空公司塗裝的模型（生 AI 交通用）。"""
        pool = [m for m in self.models if m.airline]
        if prefer_types:
            pool = [m for m in pool if m.type_code in prefer_types] or pool
        return random.choice(pool) if pool else None
