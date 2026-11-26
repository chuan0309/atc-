"""把乾淨的語音加工成「無線電」聲：帶通濾波 + 輕微失真 + 底噪。"""
from __future__ import annotations

import numpy as np


def _bandpass(x: np.ndarray, sr: int, lo: float = 300.0, hi: float = 3000.0) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    spec[(freqs < lo) | (freqs > hi)] = 0
    return np.fft.irfft(spec, n=len(x))


def apply_radio_effect(pcm16: bytes, sr: int, noise: float = 0.015, seed: int | None = None) -> bytes:
    x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if x.size == 0:
        return pcm16
    x = _bandpass(x, sr)
    x = np.tanh(x * 2.5) / np.tanh(2.5)  # 壓縮/輕微失真
    rng = np.random.default_rng(seed)
    x = x + rng.normal(0, noise, x.shape)
    # 前後加一點點 squelch 雜訊
    tail = rng.normal(0, noise * 4, int(sr * 0.08)).astype(np.float32)
    x = np.concatenate([tail, x, tail])
    x = np.clip(x * 0.9, -1, 1)
    return (x * 32767).astype(np.int16).tobytes()
