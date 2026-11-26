"""主程式：把模擬器、GSX、AI 交通、Gemini、語音串起來。"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from .brain import ATCBrain, ATCResponse
from .config import Config
from .gsx import GSX
from .phases import Phase, PhaseTracker
from .sim import SimInterface
from .simbrief import FlightPlan

log = logging.getLogger(__name__)

# 進入這些階段時，ATC 會主動呼叫你（交接、許可等）
PHASE_EVENTS = {
    Phase.DEPARTURE: "Aircraft just became airborne. Tower: instruct the aircraft to contact departure with frequency.",
    Phase.CRUISE: "Aircraft is climbing through the upper levels. Departure: hand off to center with frequency.",
    Phase.DESCENT: "Aircraft has started descent near top of descent. Center: issue descent clearance and STAR/arrival info if not given.",
    Phase.APPROACH: "Aircraft is below 10000 ft near destination. Center: hand off to approach with frequency.",
    Phase.LANDING: "Aircraft is on final approach. Approach: hand off to tower; if already with tower, tower gives landing clearance (or sequencing if AI traffic is ahead).",
    Phase.TAXI_IN: "Aircraft has landed and is vacating. Tower: instruct to vacate and contact ground with frequency.",
}

# 哪些階段在出發機場 / 目的地機場放 AI 交通
ORIGIN_PHASES = {Phase.PREFLIGHT, Phase.PUSHBACK, Phase.TAXI_OUT, Phase.TAKEOFF, Phase.DEPARTURE}
DEST_PHASES = {Phase.APPROACH, Phase.LANDING, Phase.TAXI_IN, Phase.PARKED}


@dataclass
class Transmission:
    audio_wav: bytes | None = None
    text: str | None = None
    event: str | None = None


class ATCApp:
    def __init__(self, cfg: Config, sim: SimInterface, plan: FlightPlan, brain: ATCBrain,
                 tts=None, printer=print, traffic=None, runways: dict | None = None, enroute=None):
        self.cfg = cfg
        self.sim = sim
        self.plan = plan
        self.brain = brain
        self.tts = tts
        self.radio = None
        if tts is not None:
            from .radio_out import RadioOut
            self.radio = RadioOut(tts)
        self.print = printer
        self.gsx = GSX(sim, cfg.gsx_menu_file) if cfg.gsx_enabled else None
        self.tracker = PhaseTracker(plan.cruise_altitude_ft, plan.destination.elevation_ft)
        self.traffic = traffic             # TrafficManager 或 None
        self.runways = runways or {}       # {"origin": Runway, "destination": Runway}
        self.enroute = enroute             # EnrouteTraffic 或 None
        self.queue: "queue.Queue[Transmission]" = queue.Queue()
        self.running = False
        self._busy = threading.Lock()
        self._last_slow = 0.0
        self._last_t = None

    # ---- 輸入 ----
    def submit_audio(self, wav: bytes) -> None:
        self.queue.put(Transmission(audio_wav=wav))

    def submit_text(self, text: str) -> None:
        self.queue.put(Transmission(text=text))

    # ---- 處理你的呼叫 ----
    def _on_frequency(self) -> bool:
        exp = self.brain.memory.expected_frequency
        if not self.cfg.require_frequency or not exp:
            return True
        com1 = self.sim.get_state().com1_active_mhz
        return abs(com1 - exp) < 0.006

    def process(self, tx: Transmission) -> ATCResponse | None:
        if not tx.event and not self._on_frequency():
            self.print(f"  (COM1 沒調到 {self.brain.memory.expected_frequency:.3f}，沒人回你)")
            return None
        state = self.sim.get_state()
        traffic = self.traffic.summary(state) if self.traffic else "no AI traffic"
        if self.enroute:
            traffic = "\n".join(x for x in (traffic, self.enroute.summary(state)) if x)
        with self._busy:
            try:
                r = self.brain.handle(
                    phase=self.tracker.phase,
                    controller=self.tracker.controller,
                    sim_brief=state.brief(),
                    gsx_status=self.gsx.status_text() if self.gsx else "not used",
                    audio_wav=tx.audio_wav, text=tx.text, event=tx.event,
                    traffic=traffic,
                )
            except Exception as e:  # noqa: BLE001
                log.error("Gemini 呼叫失敗: %s", e)
                self.print(f"  [錯誤] Gemini 呼叫失敗: {e}")
                return None
        if r.pilot_transcript and not tx.event:
            self.print(f"PILOT    : {r.pilot_transcript}")
        if r.respond and r.atc_text:
            self.print(f"{r.controller.upper():<9}: {r.atc_text}")
            if self.radio:
                self.radio.say_atc(r.atc_text, r.controller)
        self._apply(r)
        return r

    def _apply(self, r: ATCResponse) -> None:
        if r.next_phase:
            try:
                if self.tracker.force(Phase(r.next_phase)):
                    log.info("階段 -> %s", r.next_phase)
            except ValueError:
                pass
        if r.approve_pushback:
            self.tracker.force(Phase.PUSHBACK)
            if self.gsx and self.cfg.gsx_auto_pushback:
                if self.gsx.request_pushback():
                    self.print("  [GSX] 已幫你叫推車")
        if self.traffic and r.runway_clearance in ("lineup", "takeoff", "landing"):
            self.traffic.player_reservation = "landing" if r.runway_clearance == "landing" else "takeoff"

    # ---- 定時更新 ----
    def _active_runway(self):
        p = self.tracker.phase
        if p in ORIGIN_PHASES:
            return self.runways.get("origin")
        if p in DEST_PHASES:
            return self.runways.get("destination")
        return None

    def tick(self, dt: float = 1.0, slow: bool = True) -> None:
        state = self.sim.get_state()
        if slow:
            new_phase = self.tracker.update(state)
            if new_phase:
                self.print(f"  -- 階段: {new_phase.value} (管制: {self.tracker.controller}) --")
                if new_phase in PHASE_EVENTS:
                    self.queue.put(Transmission(event=PHASE_EVENTS[new_phase]))
            if self.gsx:
                for ev in self.gsx.poll():
                    if ev.old.name != "UNKNOWN":
                        self.print(f"  [{ev.describe()}]")
        if self.traffic:
            self.traffic.set_runway(self._active_runway())
            self.traffic.update(state, dt)
            for call in self.traffic.pop_radio():
                who = "TWR" if call.speaker == "atc" else call.callsign
                self.print(f"  ({who}: {call.text})")
                if self.radio:
                    self.radio.say_ai(call.speaker, call.controller, call.text, call.callsign)
        if self.enroute and slow:
            self.enroute.update(state, dt)

    def drain(self) -> None:
        while True:
            try:
                tx = self.queue.get_nowait()
            except queue.Empty:
                return
            self.process(tx)

    def _worker(self) -> None:
        while self.running:
            try:
                tx = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.process(tx)

    def run_forever(self, tick_s: float = 0.2) -> None:
        """AI 飛機每 0.2 秒動一次；階段/GSX 每秒檢查；Gemini 在另一個執行緒，不會卡住 AI 移動。"""
        self.running = True
        threading.Thread(target=self._worker, daemon=True).start()
        last = time.time()
        while self.running:
            now = time.time()
            dt, last = now - last, now
            slow = now - self._last_slow >= 1.0
            if slow:
                self._last_slow = now
            try:
                self.tick(dt, slow)
            except Exception as e:  # noqa: BLE001
                log.exception("tick 出錯: %s", e)
            time.sleep(tick_s)
        if self.traffic:
            self.traffic.clear()
        if self.enroute:
            self.enroute.clear()
