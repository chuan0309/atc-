"""真實航班班表。

來源（可以同時用）：
1. AeroDataBox API（RapidAPI，有免費方案，要 API key）：抓你出發/目的地機場的真實起降班表
2. 自己的 CSV 檔：每天重複的班表，格式見 schedule.example.csv

拿到的是：航班號/呼號、航空公司、機型、起飛機場、降落機場、表定時間（UTC）。
飛機本身由我們的交通引擎飛，所以 ATC 能真的指揮它們。
"""
from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".gemini-atc" / "schedules"


@dataclass
class ScheduledFlight:
    callsign: str          # ICAO 呼號，例如 CAL100
    airline: str           # ICAO 航空公司，例如 CAL
    number: str            # 數字部分，例如 100
    type_code: str         # ICAO 機型，例如 A333
    origin: str            # ICAO
    destination: str       # ICAO
    dep_utc: datetime | None = None
    arr_utc: datetime | None = None

    @property
    def key(self) -> str:
        d = self.dep_utc or self.arr_utc
        return f"{self.callsign}-{d:%Y%m%d%H%M}" if d else self.callsign


# ---------- 機型名稱 -> ICAO 代碼 ----------
_MODEL_RULES = [
    (r"A220-100|BCS1", "BCS1"), (r"A220-300|BCS3", "BCS3"),
    (r"A319\s*neo|A319N", "A19N"), (r"A320\s*neo|A320N", "A20N"), (r"A321\s*neo|A321N|A321XLR|A321LR", "A21N"),
    (r"A318", "A318"), (r"A319", "A319"), (r"A320", "A320"), (r"A321", "A321"),
    (r"A330-200|A332", "A332"), (r"A330-300|A333", "A333"), (r"A330-900|A339", "A339"), (r"A330-800|A338", "A338"),
    (r"A340-300|A343", "A343"), (r"A340-600|A346", "A346"),
    (r"A350-1000|A35K", "A35K"), (r"A350", "A359"), (r"A380|A388", "A388"),
    (r"737\s*MAX\s*8|737-8\b|B38M", "B38M"), (r"737\s*MAX\s*9|737-9\b|B39M", "B39M"),
    (r"737-700|B737", "B737"), (r"737-800|B738", "B738"), (r"737-900|B739", "B739"),
    (r"747-8|B748", "B748"), (r"747-400|B744", "B744"),
    (r"757-200|B752", "B752"), (r"767-300|B763", "B763"),
    (r"777-300ER|B77W", "B77W"), (r"777F|B77L", "B77L"), (r"777-200|B772", "B772"), (r"777-300|B773", "B773"),
    (r"787-8|B788", "B788"), (r"787-9|B789", "B789"), (r"787-10|B78X", "B78X"),
    (r"E190|ERJ-190|Embraer 190", "E190"), (r"E195|Embraer 195", "E195"), (r"E175|Embraer 175", "E175"),
    (r"ATR 72|AT7", "AT76"), (r"Dash 8|DHC-8-400|Q400", "DH8D"),
    (r"CRJ-900|CRJ9", "CRJ9"), (r"CRJ-700|CRJ7", "CRJ7"),
]


def model_to_icao(model: str) -> str:
    m = (model or "").strip()
    if re.fullmatch(r"[A-Z][A-Z0-9]{2,3}", m):
        return m
    for pat, code in _MODEL_RULES:
        if re.search(pat, m, re.I):
            return code
    return ""


def split_callsign(cs: str) -> tuple[str, str]:
    m = re.match(r"([A-Z]{3})\s*0*(\w+)", (cs or "").upper().replace(" ", ""))
    return (m.group(1), m.group(2)) if m else ("", "")


def _parse_dt(v) -> datetime | None:
    if isinstance(v, dict):
        v = v.get("utc")
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------- AeroDataBox ----------
def parse_aerodatabox(data: dict, airport: str) -> list[ScheduledFlight]:
    """解析 AeroDataBox 機場起降資料。欄位名稱是照公開文件常見格式寫的，缺欄位就跳過。"""
    out = []
    for direction in ("departures", "arrivals"):
        for item in data.get(direction, []) or []:
            if item.get("isCargo") and not item.get("callSign"):
                continue
            airline = (item.get("airline") or {}).get("icao", "") or ""
            cs = (item.get("callSign") or "").replace(" ", "").upper()
            a, num = split_callsign(cs)
            if not a:
                a = airline.upper()
                num = re.sub(r"\D", "", item.get("number", "")) or ""
                cs = f"{a}{num}" if a and num else ""
            if not cs:
                continue
            type_code = model_to_icao((item.get("aircraft") or {}).get("model", ""))
            # departure/arrival 兩邊的 movement；新舊格式都試
            dep = item.get("departure") or (item.get("movement") if direction == "departures" else None) or {}
            arr = item.get("arrival") or (item.get("movement") if direction == "arrivals" else None) or {}
            other = (item.get("movement") or {}).get("airport", {}).get("icao", "")
            if direction == "departures":
                origin = airport
                dest = (arr.get("airport") or {}).get("icao") or other
                dep_t = _parse_dt(dep.get("revisedTime")) or _parse_dt(dep.get("scheduledTime"))
                arr_t = _parse_dt(arr.get("revisedTime")) or _parse_dt(arr.get("scheduledTime")) if "arrival" in item else None
            else:
                dest = airport
                origin = (dep.get("airport") or {}).get("icao") or other
                arr_t = _parse_dt(arr.get("revisedTime")) or _parse_dt(arr.get("scheduledTime"))
                dep_t = _parse_dt(dep.get("revisedTime")) or _parse_dt(dep.get("scheduledTime")) if "departure" in item else None
            status = (item.get("status") or "").lower()
            if status in ("canceled", "cancelled", "diverted"):
                continue
            out.append(ScheduledFlight(cs, a or airline, num, type_code, origin or "", dest or "", dep_t, arr_t))
    return out


class AeroDataBoxProvider:
    HOST = "aerodatabox.p.rapidapi.com"

    def __init__(self, api_key: str, host: str = HOST):
        self.api_key = api_key
        self.host = host

    def fetch(self, icao: str, hours_back: int = 2, hours_ahead: int = 10) -> list[ScheduledFlight]:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        cache = CACHE_DIR / f"adb_{icao}_{now:%Y%m%d%H}.json"
        if cache.exists():
            data = json.loads(cache.read_text())
        else:
            url = f"https://{self.host}/flights/airports/icao/{icao}"
            params = {"offsetMinutes": -60 * hours_back, "durationMinutes": 60 * (hours_back + hours_ahead),
                      "withLeg": "true", "direction": "Both", "withCancelled": "false",
                      "withCodeshared": "false", "withCargo": "true", "withPrivate": "false"}
            headers = {"X-RapidAPI-Key": self.api_key, "X-RapidAPI-Host": self.host}
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            cache.write_text(json.dumps(data))
        flights = parse_aerodatabox(data, icao)
        log.info("AeroDataBox %s: %d 班", icao, len(flights))
        return flights


# ---------- CSV ----------
def parse_schedule_csv(text: str, day: datetime) -> list[ScheduledFlight]:
    """CSV 欄位：callsign,type,origin,destination,dep_utc,arr_utc（時間 HH:MM，每天重複）。"""
    out = []
    base = day.astimezone(timezone.utc).date()
    for row in csv.DictReader(io_lines(text)):
        cs = row.get("callsign", "").strip().upper()
        a, num = split_callsign(cs)
        if not a:
            continue

        def at(v):
            v = (v or "").strip()
            if not v:
                return None
            hh, mm = v.split(":")[:2]
            return datetime.combine(base, time(int(hh), int(mm)), timezone.utc)

        dep, arr = at(row.get("dep_utc")), at(row.get("arr_utc"))
        if dep and arr and arr < dep:
            arr += timedelta(days=1)
        out.append(ScheduledFlight(cs, a, num, model_to_icao(row.get("type", "").strip()),
                                   row.get("origin", "").strip().upper(), row.get("destination", "").strip().upper(),
                                   dep, arr))
    return out


def io_lines(text: str):
    return [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


class CSVScheduleProvider:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch_all(self, now: datetime | None = None) -> list[ScheduledFlight]:
        now = now or datetime.now(timezone.utc)
        text = self.path.read_text(encoding="utf-8")
        # 昨天/今天/明天都產生，跨午夜才不會漏
        out = []
        for d in (-1, 0, 1):
            out += parse_schedule_csv(text, now + timedelta(days=d))
        return out


class Schedule:
    """合併所有班表來源，去掉重複。"""

    def __init__(self, flights: list[ScheduledFlight] | None = None):
        self.flights: dict[str, ScheduledFlight] = {}
        for f in flights or []:
            self.add(f)

    def add(self, f: ScheduledFlight) -> None:
        old = self.flights.get(f.key)
        if old is None:
            self.flights[f.key] = f
            return
        # 合併：補上缺的欄位
        for k, v in asdict(f).items():
            if v and not getattr(old, k):
                setattr(old, k, v)

    def extend(self, flights) -> None:
        for f in flights:
            self.add(f)

    def __len__(self):
        return len(self.flights)

    def departures(self, icao: str) -> list[ScheduledFlight]:
        return sorted((f for f in self.flights.values() if f.origin == icao and f.dep_utc),
                      key=lambda f: f.dep_utc)

    def arrivals(self, icao: str) -> list[ScheduledFlight]:
        return sorted((f for f in self.flights.values() if f.destination == icao and f.arr_utc),
                      key=lambda f: f.arr_utc)

    def airborne(self, now: datetime) -> list[ScheduledFlight]:
        return [f for f in self.flights.values() if f.dep_utc and f.arr_utc and f.dep_utc <= now <= f.arr_utc]


def load_schedule(cfg, airports: list[str]) -> Schedule:
    """依 config 把各種來源的班表合在一起。任何一個來源失敗都不影響其他的。"""
    sched = Schedule()
    if cfg.schedule_csv:
        try:
            sched.extend(CSVScheduleProvider(cfg.schedule_csv).fetch_all())
        except Exception as e:  # noqa: BLE001
            log.warning("讀班表 CSV 失敗: %s", e)
    if cfg.schedule_aerodatabox_key:
        prov = AeroDataBoxProvider(cfg.schedule_aerodatabox_key)
        for icao in dict.fromkeys(a for a in airports if a):
            try:
                sched.extend(prov.fetch(icao))
            except Exception as e:  # noqa: BLE001
                log.warning("AeroDataBox %s 失敗: %s", icao, e)
    return sched
