"""Push-to-talk：鍵盤按鍵或搖桿按鈕，按住講話、放開送出。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)


class PushToTalk:
    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None],
                 key: str = "caps lock", joystick: int = -1, button: int = -1):
        self.on_press = on_press
        self.on_release = on_release
        self.key = key
        self.joystick = joystick
        self.button = button
        self._down = False

    def _press(self):
        if not self._down:
            self._down = True
            self.on_press()

    def _release(self):
        if self._down:
            self._down = False
            self.on_release()

    def start(self) -> None:
        if self.joystick >= 0 and self.button >= 0:
            threading.Thread(target=self._joystick_loop, daemon=True).start()
            log.info("PTT：搖桿 %d 按鈕 %d", self.joystick, self.button)
        if self.key:
            import keyboard  # Windows 上不用管理員；Linux 需要 root

            keyboard.on_press_key(self.key, lambda e: self._press(), suppress=False)
            keyboard.on_release_key(self.key, lambda e: self._release(), suppress=False)
            log.info("PTT：按住 [%s] 講話", self.key)

    def _joystick_loop(self) -> None:
        import os

        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame

        pygame.init()
        pygame.joystick.init()
        js = pygame.joystick.Joystick(self.joystick)
        js.init()
        while True:
            pygame.event.pump()
            if js.get_button(self.button):
                self._press()
            else:
                self._release()
            time.sleep(0.02)
