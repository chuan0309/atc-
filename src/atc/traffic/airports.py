"""機場座標（OurAirports 公開資料），空中交通算航線要用。"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
CACHE = Path.home() / ".gemini-atc" / "airports.csv"


@dataclass(frozen=True)
class AirportPos:
    icao: str
    lat: float
    lon: float
    elevation_ft: float


def parse_airports(text: str) -> dict[str, AirportPos]:
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("type") not in ("large_airport", "medium_airport"):
            continue
        icao = row.get("icao_code") or row.get("ident")
        try:
            out[icao] = AirportPos(icao, float(row["latitude_deg"]), float(row["longitude_deg"]),
                                   float(row["elevation_ft"] or 0))
        except (TypeError, ValueError):
            continue
    return out


def load_airports(cache: Path = CACHE) -> dict[str, AirportPos]:
    try:
        if not cache.exists():
            log.info("下載機場資料 (OurAirports)...")
            r = requests.get(AIRPORTS_URL, timeout=120)
            r.raise_for_status()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text, encoding="utf-8")
        return parse_airports(cache.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("讀機場資料失敗: %s", e)
        return {}
