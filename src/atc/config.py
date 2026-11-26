from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_VOICES = {
    "delivery": "Kore",
    "ground": "Puck",
    "tower": "Charon",
    "departure": "Fenrir",
    "center": "Orus",
    "approach": "Aoede",
}


@dataclass
class Config:
    api_key: str = ""
    brain_model: str = "gemini-2.5-flash"
    tts_model: str = "gemini-2.5-flash-preview-tts"
    voices: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_VOICES))
    simbrief_username: str = ""
    simbrief_user_id: str = ""
    sim_backend: str = "msfs"
    gsx_enabled: bool = True
    gsx_auto_pushback: bool = True
    gsx_menu_file: str = ""
    ptt_key: str = "caps lock"
    ptt_joystick: int = -1
    ptt_button: int = -1
    radio_effect: bool = True
    require_frequency: bool = False
    traffic_enabled: bool = True
    traffic_departures_per_hour: float = 20
    traffic_arrivals_per_hour: float = 20
    traffic_radio_chatter: bool = True
    fsltl_community_path: str = ""
    fsltl_vmr_file: str = ""
    traffic_enroute: bool = True
    traffic_enroute_radius_nm: float = 40.0
    schedule_aerodatabox_key: str = ""
    schedule_csv: str = ""

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg = cls()
        p = Path(path) if path else Path("config.toml")
        data: dict = {}
        if p.exists():
            with open(p, "rb") as f:
                data = tomllib.load(f)
        g = data.get("gemini", {})
        cfg.api_key = g.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
        cfg.brain_model = g.get("brain_model", cfg.brain_model)
        cfg.tts_model = g.get("tts_model", cfg.tts_model)
        cfg.voices.update(g.get("voices", {}))
        sb = data.get("simbrief", {})
        cfg.simbrief_username = str(sb.get("username", ""))
        cfg.simbrief_user_id = str(sb.get("user_id", ""))
        cfg.sim_backend = data.get("sim", {}).get("backend", cfg.sim_backend)
        gsx = data.get("gsx", {})
        cfg.gsx_enabled = gsx.get("enabled", cfg.gsx_enabled)
        cfg.gsx_auto_pushback = gsx.get("auto_pushback", cfg.gsx_auto_pushback)
        cfg.gsx_menu_file = gsx.get("menu_file", "")
        ptt = data.get("ptt", {})
        cfg.ptt_key = ptt.get("key", cfg.ptt_key)
        cfg.ptt_joystick = int(ptt.get("joystick", -1))
        cfg.ptt_button = int(ptt.get("button", -1))
        r = data.get("radio", {})
        cfg.radio_effect = r.get("radio_effect", cfg.radio_effect)
        cfg.require_frequency = r.get("require_frequency", cfg.require_frequency)
        t = data.get("traffic", {})
        cfg.traffic_enabled = t.get("enabled", cfg.traffic_enabled)
        cfg.traffic_departures_per_hour = float(t.get("departures_per_hour", cfg.traffic_departures_per_hour))
        cfg.traffic_arrivals_per_hour = float(t.get("arrivals_per_hour", cfg.traffic_arrivals_per_hour))
        cfg.traffic_radio_chatter = t.get("radio_chatter", cfg.traffic_radio_chatter)
        cfg.fsltl_community_path = t.get("community_path", "")
        cfg.fsltl_vmr_file = t.get("vmr_file", "")
        cfg.traffic_enroute = t.get("enroute", cfg.traffic_enroute)
        cfg.traffic_enroute_radius_nm = float(t.get("enroute_radius_nm", cfg.traffic_enroute_radius_nm))
        sc = data.get("schedule", {})
        cfg.schedule_aerodatabox_key = sc.get("aerodatabox_key") or os.environ.get("AERODATABOX_KEY", "")
        cfg.schedule_csv = sc.get("csv_file", "")
        return cfg
