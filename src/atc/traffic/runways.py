"""跑道資料：從 OurAirports 公開資料抓（第一次會下載後快取）。"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
CACHE = Path.home() / ".gemini-atc" / "runways.csv"


@dataclass
class Runway:
    airport: str
    ident: str            # 這一端，例如 "05L"
    lat: float            # 跑道頭座標
    lon: float
    heading_true: float
    elevation_ft: float
    length_ft: float
    end_lat: float        # 另一端
    end_lon: float

    @property
    def length_nm(self) -> float:
        return self.length_ft / 6076.12


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def parse_runways(text: str, icao: str) -> list[Runway]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if row["airport_ident"] != icao or row.get("closed") == "1" or not row["le_latitude_deg"]:
            continue
        le = dict(lat=_f(row["le_latitude_deg"]), lon=_f(row["le_longitude_deg"]))
        he = dict(lat=_f(row["he_latitude_deg"]), lon=_f(row["he_longitude_deg"]))
        length = _f(row["length_ft"])
        out.append(Runway(icao, row["le_ident"], le["lat"], le["lon"], _f(row["le_heading_degT"]),
                          _f(row["le_elevation_ft"]), length, he["lat"], he["lon"]))
        out.append(Runway(icao, row["he_ident"], he["lat"], he["lon"], _f(row["he_heading_degT"]),
                          _f(row["he_elevation_ft"]), length, le["lat"], le["lon"]))
    return out


def _load_csv(cache: Path = CACHE) -> str:
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    log.info("下載跑道資料 (OurAirports)...")
    r = requests.get(RUNWAYS_URL, timeout=60)
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text, encoding="utf-8")
    return r.text


def load_runways(icao: str, cache: Path = CACHE) -> list[Runway]:
    try:
        return parse_runways(_load_csv(cache), icao)
    except Exception as e:  # noqa: BLE001
        log.warning("讀跑道資料失敗: %s", e)
        return []


def pick_runway(runways: list[Runway], ident: str = "") -> Runway | None:
    for r in runways:
        if ident and r.ident == ident:
            return r
    return max(runways, key=lambda r: r.length_ft) if runways else None
