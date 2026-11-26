"""ATC 的大腦：用 Gemini 聽懂飛行員講什麼，並產生管制員的回覆。

一次呼叫同時做兩件事（省延遲）：
1. 把你的語音轉成文字（pilot_transcript）
2. 判斷內容、檢查覆誦、產生 ATC 回覆（atc_text）
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field

from .phases import Phase
from .simbrief import FlightPlan

log = logging.getLogger(__name__)

CONTROLLERS = ["delivery", "ground", "tower", "departure", "center", "approach"]

SYSTEM_PROMPT = """You are a realistic, professional air traffic controller for a flight simulator (like a real-world IFR ATC service).
You play ALL controller positions: clearance delivery, ground, tower, departure, center, approach.

Rules:
- Use standard ICAO/FAA radiotelephony phraseology, concise, like real ATC. Always address the aircraft by its radio callsign.
- Numbers spoken the aviation way in atc_text (e.g. "flight level three five zero", "squawk four five two one", "one two four decimal five").
- Only answer as the controller position that matches the current phase unless the pilot was told to contact another one.
- If the pilot readback is wrong or missing a required item (altitude, heading, squawk, runway, hold short), correct them.
- If the pilot's transmission is unintelligible or not addressed to you, respond "Say again" style or set respond=false.
- When handing off, give the next frequency and remember it. Invent realistic frequencies for the airports involved and stay consistent (see known_frequencies).
- IFR clearance format (CRAFT): Cleared to <dest>, via <SID>/<route>, climb <initial alt>, expect <cruise> 10 minutes after departure, departure frequency, squawk.
- AI TRAFFIC: a traffic picture of other aircraft at the active runway is provided. Use it to sequence the player realistically:
  only one aircraft on the runway at a time; if the runway is occupied or an arrival is close, tell the player to hold short / line up and wait / continue (number 2, traffic to follow) / go around.
  Mention relevant traffic ("traffic is an A321 on 4 mile final"). Never clear the player onto an occupied runway.
- Be brief. One transmission at a time. Never explain things to the user out of character.
- For system events (ATC-initiated calls such as handoffs, descent clearance, landing clearance, taxi after landing) produce the transmission a real controller would make at that moment; set respond=false if a real controller would stay silent.

Reply ONLY with a JSON object with these keys:
{
  "pilot_transcript": string,           // exact words the pilot said ("" for system events)
  "respond": boolean,                   // false = ATC stays silent
  "controller": "delivery|ground|tower|departure|center|approach",
  "atc_text": string,                   // what ATC says on the radio
  "readback_correct": boolean|null,
  "assigned_altitude_ft": integer|null,
  "assigned_heading": integer|null,
  "assigned_squawk": string|null,
  "assigned_runway": string|null,
  "handoff_frequency_mhz": number|null, // frequency the pilot is told to contact
  "handoff_controller": string|null,
  "next_phase": "preflight|pushback|taxi_out|takeoff|departure|cruise|descent|approach|landing|taxi_in|parked"|null,
  "approve_pushback": boolean,          // true only in the transmission that approves pushback
  "runway_clearance": "lineup|takeoff|landing"|null  // set when THIS transmission clears the player onto/for the runway
}
"""


@dataclass
class ATCResponse:
    pilot_transcript: str = ""
    respond: bool = False
    controller: str = "ground"
    atc_text: str = ""
    readback_correct: bool | None = None
    assigned_altitude_ft: int | None = None
    assigned_heading: int | None = None
    assigned_squawk: str | None = None
    assigned_runway: str | None = None
    handoff_frequency_mhz: float | None = None
    handoff_controller: str | None = None
    next_phase: str | None = None
    approve_pushback: bool = False
    runway_clearance: str | None = None

    @classmethod
    def from_json(cls, text: str) -> "ATCResponse":
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError(f"Gemini 沒回 JSON: {text[:200]}")
        data = json.loads(m.group(0))
        known = {k: data.get(k) for k in cls.__dataclass_fields__ if k in data}
        r = cls(**known)
        r.respond = bool(r.respond)
        r.approve_pushback = bool(r.approve_pushback)
        if r.controller not in CONTROLLERS:
            r.controller = "ground"
        return r


@dataclass
class ATCMemory:
    squawk: str = field(default_factory=lambda: f"{random.randint(1, 6)}{random.randint(0, 7)}{random.randint(0, 7)}{random.randint(0, 7)}")
    cleared: bool = False
    altitude_ft: int | None = None
    heading: int | None = None
    runway: str | None = None
    frequencies: dict[str, float] = field(default_factory=dict)
    expected_frequency: float | None = None

    def apply(self, r: ATCResponse) -> None:
        if r.assigned_altitude_ft:
            self.altitude_ft = r.assigned_altitude_ft
        if r.assigned_heading is not None:
            self.heading = r.assigned_heading
        if r.assigned_squawk:
            self.squawk = r.assigned_squawk
            self.cleared = True
        if r.assigned_runway:
            self.runway = r.assigned_runway
        if r.handoff_frequency_mhz:
            self.expected_frequency = float(r.handoff_frequency_mhz)
            if r.handoff_controller:
                self.frequencies[r.handoff_controller] = float(r.handoff_frequency_mhz)

    def describe(self) -> str:
        return json.dumps({
            "squawk_to_assign": self.squawk,
            "ifr_clearance_given": self.cleared,
            "current_assigned_altitude_ft": self.altitude_ft,
            "current_assigned_heading": self.heading,
            "runway": self.runway,
            "known_frequencies": self.frequencies,
        })


class ATCBrain:
    def __init__(self, api_key: str, model: str, plan: FlightPlan, client=None, max_history: int = 30):
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self.client = client
        self.model = model
        self.plan = plan
        self.memory = ATCMemory()
        self.history: list = []
        self.max_history = max_history

    def _context(self, phase: Phase, controller: str, sim_brief: str, gsx_status: str, traffic: str = "none") -> str:
        return (
            f"FLIGHT PLAN: {self.plan.summary()}\n"
            f"Suggested initial climb: {self.plan.initial_altitude_ft} ft (adjust to realistic SID altitude if known).\n"
            f"CURRENT PHASE: {phase.value}; expected controller: {controller}\n"
            f"AIRCRAFT STATE: {sim_brief}\n"
            f"GSX GROUND SERVICES: {gsx_status}\n"
            f"ATC MEMORY: {self.memory.describe()}\n"
            f"AI TRAFFIC:\n{traffic}\n"
        )

    def handle(
        self,
        *,
        phase: Phase,
        controller: str,
        sim_brief: str,
        gsx_status: str = "unknown",
        audio_wav: bytes | None = None,
        text: str | None = None,
        event: str | None = None,
        traffic: str = "none",
    ) -> ATCResponse:
        from google.genai import types

        ctx = self._context(phase, controller, sim_brief, gsx_status, traffic)
        parts = [types.Part.from_text(text=ctx)]
        if event:
            parts.append(types.Part.from_text(text=f"SYSTEM EVENT (no pilot transmission): {event}"))
        elif audio_wav:
            parts.append(types.Part.from_text(text="PILOT TRANSMISSION (audio follows). Transcribe it exactly, then respond as ATC."))
            parts.append(types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"))
        elif text:
            parts.append(types.Part.from_text(text=f"PILOT TRANSMISSION: {text}"))
        else:
            raise ValueError("需要 audio、text 或 event")

        contents = self.history + [types.Content(role="user", parts=parts)]
        resp = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
        raw = resp.text or ""
        r = ATCResponse.from_json(raw)
        log.debug("Gemini: %s", raw)

        # 歷史只存文字（不存語音，省 token）
        user_note = f"[{phase.value}] " + (f"EVENT: {event}" if event else f"PILOT: {r.pilot_transcript or text}")
        self.history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_note)]))
        self.history.append(types.Content(role="model", parts=[types.Part.from_text(text=raw)]))
        self.history = self.history[-self.max_history:]

        self.memory.apply(r)
        return r
