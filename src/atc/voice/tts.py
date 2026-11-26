"""Gemini TTS：把 ATC 的文字念出來，每個管制席位不同聲音。"""
from __future__ import annotations

import logging

from .radio_fx import apply_radio_effect

log = logging.getLogger(__name__)

TTS_SAMPLE_RATE = 24000  # Gemini TTS 輸出 24kHz 16-bit mono PCM


class GeminiTTS:
    def __init__(self, client, model: str, voices: dict[str, str], radio_effect: bool = True):
        self.client = client
        self.model = model
        self.voices = voices
        self.radio_effect = radio_effect

    def synthesize(self, text: str, controller: str = "", voice: str | None = None, pilot: bool = False) -> bytes:
        from google.genai import types

        voice = voice or self.voices.get(controller, "Kore")
        who = "airline pilot" if pilot else "air traffic controller"
        prompt = f"Say in a calm, fast, professional {who} radio voice: {text}"
        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )
        pcm = resp.candidates[0].content.parts[0].inline_data.data
        if self.radio_effect:
            pcm = apply_radio_effect(pcm, TTS_SAMPLE_RATE)
        return pcm

    def speak(self, text: str, controller: str = "", voice: str | None = None, pilot: bool = False) -> None:
        from .audio import play_pcm

        try:
            play_pcm(self.synthesize(text, controller, voice, pilot), TTS_SAMPLE_RATE)
        except Exception as e:  # noqa: BLE001
            log.error("TTS 失敗（文字仍會顯示）: %s", e)
