"""把數字、跑道念成無線電講法，給 TTS 用。"""
from __future__ import annotations

import re

DIGITS = "zero one two three four five six seven eight niner".split()
SIDE = {"L": "left", "R": "right", "C": "center"}


def say_digits(s: str) -> str:
    return " ".join(DIGITS[int(c)] if c.isdigit() else c for c in s)


def say_runway(ident: str) -> str:
    m = re.match(r"(\d{1,2})([LRC]?)", ident.upper())
    if not m:
        return ident
    num, side = m.groups()
    return (say_digits(num.zfill(2)) + (" " + SIDE[side] if side else "")).strip()


def say_callsign(radio_callsign: str) -> str:
    """'Dynasty 123' -> 'Dynasty one two three'"""
    return re.sub(r"\d+", lambda m: say_digits(m.group(0)), radio_callsign)
