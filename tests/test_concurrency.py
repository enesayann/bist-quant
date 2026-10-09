import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pandas as pd

from bot import scheduler, storage, telegram_bot
from tests.helpers import OfflineTestCase, position_state


class ScanCommandTests(OfflineTestCase):
    def test_scan_and_manual_commands_cannot_overwrite_each_other(self):
        for command in ("al", "sat"):
            with self.subTest(command=command):
                storage.pozisyon_takip_kaydet(position_state())
                scan_ready, command_ready, release = threading.Event(), threading.Event(), threading.Event()

                def analyze(symbol, signals, state):
                    state["acik"][0]["guncel_stop"] = 90
                    scan_ready.set()
                    if not release.wait(5):
                        raise RuntimeError("Test scan barrier timed out")

                def run_command():
                    command_ready.set()
                    return telegram_bot.komut_al(["THYAO", "100", "10"]) if command == "al" else telegram_bot.komut_sat(["ASELS"])

                with patch("bot.scheduler.piyasa_acik_mi", return_value=True), patch("bot.scheduler.hisseler", ["ASELS.IS"]), patch("bot.scheduler.analiz_et", side_effect=analyze), patch("bot.telegram_bot.tek_hisse_veri_getir", return_value=pd.DataFrame({"ATR": [2.], "Close": [105.]})), ThreadPoolExecutor(max_workers=2) as executor:
                    scan = executor.submit(scheduler.ana_tarama)
                    self.assertTrue(scan_ready.wait(5))
                    manual = executor.submit(run_command)
                    self.assertTrue(command_ready.wait(5))
                    try:
                        self.assertFalse(manual.done())
                    finally:
                        release.set()
                    scan.result(timeout=5)
                    self.assertIn("✅", manual.result(timeout=5))
                state = storage.pozisyon_takip_yukle()
                if command == "al":
                    self.assertEqual({p["hisse"] for p in state["acik"]}, {"ASELS.IS", "THYAO.IS"})
                    self.assertEqual(state["acik"][0]["guncel_stop"], 90)
                else:
                    self.assertEqual(state["acik"], [])
                    self.assertEqual(state["kapanan"][0]["guncel_stop"], 90)
                    self.assertEqual(state["kapanan"][0]["pnl_yuzde"], 5)
