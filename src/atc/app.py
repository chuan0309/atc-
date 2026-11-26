"""主程式：把模擬器、GSX、Gemini、語音串起來。"""
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
    Phase.LANDING: "Aircraft is on final approach. Approach: hand off to tower; if already with tower, tower gives landing clearance with wind.",
    Phase.TAXI_IN: "Aircraft has landed and is vacating. Tower: instruct to vacate and contact ground with frequency.",
}


@dataclass
class Transmission:
    audio_wav: bytes | None = None
    text: str | None = None
    event: str | None = None


class ATCApp:
    def __init__(self, cfg: Config, sim: SimInterface, plan: FlightPlan, brain: ATCBrain,
                 tts=None, printer=print):
        self.cfg = cfg
        self.sim = sim
        self.plan = plan
        self.brain = brain
        self.tts = tts
        self.print = printer
        self.gsx = GSX(sim, cfg.gsx_menu_file) if cfg.gsx_enabled else None
        self.tracker = PhaseTracker(plan.cruise_altitude_ft, plan.destination.elevation_ft)
        self.queue: "queue.Queue[Transmission]" = queue.Queue()
        self.running = False
        self._busy = threading.Lock()

    # ---- 輸入 ----
    def submit_audio(self, wav: bytes) -> None:
        self.queue.put(Transmission(audio_wav=wav))

    def submit_text(self, text: str) -> None:
        self.queue.put(Transmission(text=text))

    # ---- 處理 ----
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
        with self._busy:
            try:
                r = self.brain.handle(
                    phase=self.tracker.phase,
                    controller=self.tracker.controller,
                    sim_brief=state.brief(),
                    gsx_status=self.gsx.status_text() if self.gsx else "not used",
                    audio_wav=tx.audio_wav, text=tx.text, event=tx.event,
                )
            except Exception as e:  # noqa: BLE001
                log.error("Gemini 呼叫失敗: %s", e)
                self.print(f"  [錯誤] Gemini 呼叫失敗: {e}")
                return None
        if r.pilot_transcript and not tx.event:
            self.print(f"PILOT : {r.pilot_transcript}")
        if r.respond and r.atc_text:
            self.print(f"{r.controller.upper():<9}: {r.atc_text}")
            if self.tts:
                self.tts.speak(r.atc_text, r.controller)
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

    def tick(self) -> None:
        """每秒跑一次：更新飛行階段、GSX 狀態，必要時 ATC 主動呼叫。"""
        state = self.sim.get_state()
        new_phase = self.tracker.update(state)
        if new_phase:
            self.print(f"  -- 階段: {new_phase.value} (管制: {self.tracker.controller}) --")
            if new_phase in PHASE_EVENTS:
                self.queue.put(Transmission(event=PHASE_EVENTS[new_phase]))
        if self.gsx:
            for ev in self.gsx.poll():
                if ev.old.name != "UNKNOWN":
                    self.print(f"  [{ev.describe()}]")

    def drain(self) -> None:
        while True:
            try:
                tx = self.queue.get_nowait()
            except queue.Empty:
                return
            self.process(tx)

    def run_forever(self, tick_s: float = 1.0) -> None:
        self.running = True
        while self.running:
            self.tick()
            self.drain()
            time.sleep(tick_s)
