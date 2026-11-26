"""抓 SimBrief 最新的飛行計畫 (OFP)。

API: https://www.simbrief.com/api/xml.fetcher.php?username=XXX&json=1
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

SIMBRIEF_URL = "https://www.simbrief.com/api/xml.fetcher.php"


@dataclass
class Airport:
    icao: str
    name: str = ""
    runway: str = ""
    elevation_ft: int = 0
    lat: float = 0.0
    lon: float = 0.0


@dataclass
class FlightPlan:
    callsign: str            # e.g. "EVA25"
    radio_callsign: str      # e.g. "EVA AIR 25"，有的話
    airline: str
    flight_number: str
    aircraft_icao: str
    origin: Airport
    destination: Airport
    alternate: str
    route: str
    sid: str
    star: str
    cruise_altitude_ft: int
    initial_altitude_ft: int
    waypoints: list[str] = field(default_factory=list)
    pax: int = 0

    def summary(self) -> str:
        return (
            f"Callsign {self.callsign} ({self.radio_callsign}), {self.aircraft_icao}, "
            f"{self.origin.icao} rwy {self.origin.runway or '?'} -> "
            f"{self.destination.icao} rwy {self.destination.runway or '?'}, "
            f"alternate {self.alternate or 'none'}, SID {self.sid or 'none'}, "
            f"STAR {self.star or 'none'}, cruise FL{self.cruise_altitude_ft // 100:03d}, "
            f"route: {self.route}"
        )


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _airport(d: dict) -> Airport:
    return Airport(
        icao=d.get("icao_code", ""),
        name=d.get("name", ""),
        runway=d.get("plan_rwy", ""),
        elevation_ft=_int(d.get("elevation")),
        lat=_float(d.get("pos_lat")),
        lon=_float(d.get("pos_long")),
    )


def parse_ofp(ofp: dict) -> FlightPlan:
    general = ofp.get("general", {})
    atc = ofp.get("atc", {})
    fixes = ofp.get("navlog", {}).get("fix", [])
    if isinstance(fixes, dict):
        fixes = [fixes]

    sid = star = ""
    waypoints: list[str] = []
    for fx in fixes:
        ident = fx.get("ident", "")
        if fx.get("is_sid_star") == "1":
            via = fx.get("via_airway", "")
            if fx.get("stage") == "CLB" and not sid:
                sid = via
            elif fx.get("stage") == "DSC":
                star = via
        if ident and ident not in ("TOC", "TOD") and (not waypoints or waypoints[-1] != ident):
            waypoints.append(ident)

    airline = general.get("icao_airline", "")
    fnum = general.get("flight_number", "")
    callsign = atc.get("callsign") or f"{airline}{fnum}"
    cruise = _int(general.get("initial_altitude")) or _int(general.get("cruise_altitude"))

    return FlightPlan(
        callsign=callsign,
        radio_callsign=general.get("radio_callsign", "") or callsign,
        airline=airline,
        flight_number=fnum,
        aircraft_icao=ofp.get("aircraft", {}).get("icaocode", ""),
        origin=_airport(ofp.get("origin", {})),
        destination=_airport(ofp.get("destination", {})),
        alternate=ofp.get("alternate", {}).get("icao_code", "") if isinstance(ofp.get("alternate"), dict) else "",
        route=general.get("route", ""),
        sid=sid,
        star=star,
        cruise_altitude_ft=cruise,
        # 大部分 SID 起始高度 5000 ft；真的不知道就先給 5000，讓 Gemini 依機場調整
        initial_altitude_ft=5000 if cruise > 5000 else cruise,
        waypoints=waypoints,
        pax=_int(ofp.get("weights", {}).get("pax_count")),
    )


def fetch_flight_plan(username: str = "", user_id: str = "", timeout: float = 15) -> FlightPlan:
    if not username and not user_id:
        raise ValueError("要填 SimBrief username 或 user_id")
    params = {"json": "1"}
    if user_id:
        params["userid"] = user_id
    else:
        params["username"] = username
    r = requests.get(SIMBRIEF_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    status = data.get("fetch", {}).get("status", "")
    if status and status.lower() != "success":
        raise RuntimeError(f"SimBrief 回傳錯誤: {status}")
    return parse_ofp(data)
