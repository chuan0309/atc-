"""啟動方式：
  python -m atc                 # 真的接 MSFS + 語音
  python -m atc --text          # 用打字代替講話
  python -m atc --mock --text   # 完全不用開模擬器，測試用
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading

from .config import Config
from .simbrief import Airport, FlightPlan, fetch_flight_plan

DEMO_PLAN = FlightPlan(
    callsign="EVA25", radio_callsign="EVA 25", airline="EVA", flight_number="25",
    aircraft_icao="B77W",
    origin=Airport("RCTP", "Taoyuan Intl", "05L", 106),
    destination=Airport("RJAA", "Narita Intl", "34L", 141),
    alternate="RJTT", route="PIANO1 ... (demo)", sid="", star="",
    cruise_altitude_ft=36000, initial_altitude_ft=5000,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gemini-atc")
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("--mock", action="store_true", help="不接模擬器，用假資料")
    ap.add_argument("--text", action="store_true", help="用打字代替語音")
    ap.add_argument("--no-tts", action="store_true", help="ATC 不出聲，只顯示文字")
    ap.add_argument("--demo-plan", action="store_true", help="不抓 SimBrief，用內建範例航班")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load(args.config)
    if args.mock:
        cfg.sim_backend = "mock"
    if not cfg.api_key:
        print("沒有 Gemini API key：請在 config.toml 填 api_key 或設定環境變數 GEMINI_API_KEY")
        return 1

    # 1. SimBrief
    if args.demo_plan or not (cfg.simbrief_username or cfg.simbrief_user_id):
        print("使用內建範例航班（要用自己的請在 config.toml 填 SimBrief 帳號）")
        plan = DEMO_PLAN
    else:
        plan = fetch_flight_plan(cfg.simbrief_username, cfg.simbrief_user_id)
    print(f"航班: {plan.summary()}")

    # 2. 模擬器
    from .sim import create_sim
    sim = create_sim(cfg.sim_backend)
    sim.connect()

    # 3. Gemini
    from google import genai
    from .brain import ATCBrain
    from .voice.tts import GeminiTTS
    client = genai.Client(api_key=cfg.api_key)
    brain = ATCBrain(cfg.api_key, cfg.brain_model, plan, client=client)
    tts = None if args.no_tts else GeminiTTS(client, cfg.tts_model, cfg.voices, cfg.radio_effect)

    from .app import ATCApp
    app = ATCApp(cfg, sim, plan, brain, tts=tts)

    if args.text:
        threading.Thread(target=app.run_forever, daemon=True).start()
        print("打字跟 ATC 講話，Enter 送出。/next = 假模擬器推進到下一階段，/quit 離開")
        for line in sys.stdin:
            line = line.strip()
            if line == "/quit":
                break
            if line == "/next" and cfg.sim_backend == "mock":
                print(f"  [mock] {sim.advance()}")
            elif line:
                app.submit_text(line)
        app.running = False
    else:
        from .voice.audio import Recorder
        from .voice.ptt import PushToTalk
        rec = Recorder()

        def released():
            wav = rec.stop()
            if wav:
                app.submit_audio(wav)

        PushToTalk(rec.start, released, cfg.ptt_key, cfg.ptt_joystick, cfg.ptt_button).start()
        print(f"準備好了！按住 [{cfg.ptt_key}] 講話。Ctrl+C 離開")
        try:
            app.run_forever()
        except KeyboardInterrupt:
            pass
    sim.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
