import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from bot import config, portfolio


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        config._api_warning_times.clear()
        # Fail the test if any unmocked external request escapes a fixture.
        for target in ("requests.sessions.Session.request", "requests.get", "socket.create_connection"):
            blocker = patch(target, side_effect=AssertionError("Real network calls are forbidden in tests"))
            blocker.start()
            self.addCleanup(blocker.stop)
        environment = patch.dict(os.environ, {"TELEGRAM_TOKEN": "unit-test-token", "TELEGRAM_CHAT_ID": "123"})
        environment.start()
        self.addCleanup(environment.stop)
        directory = tempfile.TemporaryDirectory()
        previous = Path.cwd()
        os.chdir(directory.name)
        self.addCleanup(directory.cleanup)
        self.addCleanup(os.chdir, previous)


def response(payload=None, text="", status=200):
    result = Mock(status_code=status, text=text)
    result.json.return_value = copy.deepcopy(payload)
    if status >= 400:
        import requests
        result.raise_for_status.side_effect = requests.HTTPError("Mock HTTP failure")
    return result


def chart_payload(length=240):
    close = 100 + np.arange(length) * 0.1 + np.sin(np.arange(length) / 3)
    return {"chart": {"error": None, "result": [{
        "meta": {"regularMarketPrice": float(close[-1])},
        "indicators": {"quote": [{"high": (close + 1).tolist(), "low": (close - 1).tolist(),
                                  "close": close.tolist(), "volume": [1000] * length}]},
    }]}}


def candle(high=110, low=100, close=105, atr=10):
    return pd.DataFrame({"High": [high], "Low": [low], "Close": [close], "ATR": [atr]})


def position_state(symbol="ASELS.IS"):
    state = {"acik": [], "kapanan": []}
    portfolio.pozisyon_ac(symbol, 100, 85, 120, 130, 10, "TEST", state, 10)
    return state
