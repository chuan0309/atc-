"""錄音 / 播放（Windows 上用 sounddevice）。"""
from __future__ import annotations

import io
import threading
import wave

SAMPLE_RATE = 16000


def pcm_to_wav(pcm16: bytes, sr: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16)
    return buf.getvalue()


class Recorder:
    """按下 PTT 呼叫 start()，放開呼叫 stop() 拿到 WAV bytes。"""

    def __init__(self, sr: int = SAMPLE_RATE):
        self.sr = sr
        self._chunks: list[bytes] = []
        self._stream = None
        self._lock = threading.Lock()

    def start(self) -> None:
        import sounddevice as sd

        self._chunks = []

        def cb(indata, frames, t, status):  # noqa: ARG001
            with self._lock:
                self._chunks.append(bytes(indata))

        self._stream = sd.RawInputStream(samplerate=self.sr, channels=1, dtype="int16", callback=cb)
        self._stream.start()

    def stop(self) -> bytes | None:
        if not self._stream:
            return None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            pcm = b"".join(self._chunks)
        if len(pcm) < self.sr * 2 * 0.3:  # 小於 0.3 秒當作誤觸
            return None
        return pcm_to_wav(pcm, self.sr)


def play_pcm(pcm16: bytes, sr: int) -> None:
    import numpy as np
    import sounddevice as sd

    sd.play(np.frombuffer(pcm16, dtype=np.int16), sr)
    sd.wait()
