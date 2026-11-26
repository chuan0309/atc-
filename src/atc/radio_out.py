"""無線電播放佇列：你的 ATC 回覆優先播，AI 交通的對話排在後面，太舊的就丟掉。"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
import zlib

log = logging.getLogger(__name__)

AI_PILOT_VOICES = ["Zephyr", "Iapetus", "Umbriel", "Algenib", "Achird", "Sadaltager", "Leda", "Enceladus"]
STALE_AI_S = 25.0


def pilot_voice(callsign: str) -> str:
    return AI_PILOT_VOICES[zlib.crc32(callsign.encode()) % len(AI_PILOT_VOICES)]


class RadioOut:
    def __init__(self, tts):
        self.tts = tts
        self.q: "queue.PriorityQueue" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def say_atc(self, text: str, controller: str, priority: int = 0) -> None:
        self.q.put((priority, next(self._seq), time.time(), dict(text=text, controller=controller)))

    def say_ai(self, speaker: str, controller: str, text: str, callsign: str) -> None:
        kw = dict(text=text, controller=controller)
        if speaker == "pilot":
            kw.update(voice=pilot_voice(callsign), pilot=True)
        self.q.put((1, next(self._seq), time.time(), kw))

    def _run(self) -> None:
        while True:
            prio, _, t, kw = self.q.get()
            if prio > 0 and time.time() - t > STALE_AI_S:
                continue
            try:
                self.tts.speak(**kw)
            except Exception as e:  # noqa: BLE001
                log.error("播放失敗: %s", e)
