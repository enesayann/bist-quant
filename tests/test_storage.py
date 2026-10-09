import json
import os
from pathlib import Path
from unittest.mock import patch

from bot import storage
from tests.helpers import OfflineTestCase, position_state


class StorageTests(OfflineTestCase):
    def test_valid_json_roundtrip(self):
        storage._json_kaydet("state.json", {"value": "Türkçe", "nested": [1, 2]})
        self.assertEqual(storage._json_yukle("state.json", {}), {"value": "Türkçe", "nested": [1, 2]})

    def test_missing_file_default_is_not_shared(self):
        default = {"items": []}
        result = storage._json_yukle("missing.json", default)
        result["items"].append(1)
        self.assertEqual(default, {"items": []})

    def test_corrupt_file_raises_and_is_preserved(self):
        path = Path("pozisyon_takip.json")
        path.write_text('{"acik": [', encoding="utf-8")
        with self.assertLogs("borsa_bot", level="ERROR"), self.assertRaises(storage.StorageError):
            storage.pozisyon_takip_yukle()
        self.assertEqual(path.read_text(encoding="utf-8"), '{"acik": [')

    def test_schema_errors_fail_closed(self):
        for invalid in ({"acik": {}, "kapanan": []}, {"acik": [{}], "kapanan": []}, []):
            Path("pozisyon_takip.json").write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertLogs("borsa_bot", level="ERROR"), self.assertRaises(storage.StorageError):
                storage.pozisyon_takip_yukle()
        state = position_state()
        state["acik"][0]["giris_fiyati"] = 0
        with self.assertLogs("borsa_bot", level="ERROR"), self.assertRaises(storage.StorageError):
            storage.pozisyon_takip_kaydet(state)

    def test_atomic_replace_is_same_directory_and_complete(self):
        Path("state.json").write_text('{"old": true}', encoding="utf-8")
        real_replace = os.replace

        def replace(source, target):
            self.assertEqual(Path(source).parent.resolve(), Path(target).parent.resolve())
            self.assertEqual(json.loads(Path(source).read_text(encoding="utf-8")), {"new": True})
            self.assertEqual(storage._json_yukle("state.json", {}), {"old": True})
            real_replace(source, target)  # also proves the temp handle is closed on Windows

        with patch("bot.storage.os.replace", side_effect=replace) as replace_mock, patch("bot.storage.os.fsync", wraps=os.fsync) as sync:
            storage._json_kaydet("state.json", {"new": True})
        replace_mock.assert_called_once()
        sync.assert_called_once()
        self.assertEqual(storage._json_yukle("state.json", {}), {"new": True})
        self.assertEqual(list(Path.cwd().glob("*.tmp")), [])

    def test_failed_replace_does_not_destroy_old_state(self):
        storage._json_kaydet("state.json", {"old": True})
        with patch("bot.storage.os.replace", side_effect=OSError("mock disk failure")), self.assertLogs("borsa_bot", level="ERROR"), self.assertRaises(storage.StorageError):
            storage._json_kaydet("state.json", {"new": True})
        self.assertEqual(storage._json_yukle("state.json", {}), {"old": True})
        self.assertEqual(list(Path.cwd().glob("*.tmp")), [])

    def test_serialization_failure_preserves_old_file(self):
        storage._json_kaydet("state.json", {"old": True})
        with self.assertLogs("borsa_bot", level="ERROR"), self.assertRaises(storage.StorageError):
            storage._json_kaydet("state.json", {"bad": float("nan")})
        self.assertEqual(storage._json_yukle("state.json", {}), {"old": True})
        self.assertEqual(list(Path.cwd().glob("*.tmp")), [])

    def test_nonfinite_json_is_rejected(self):
        Path("state.json").write_text('{"bad": NaN}', encoding="utf-8")
        with self.assertLogs("borsa_bot", level="ERROR"), self.assertRaises(storage.StorageError):
            storage._json_yukle("state.json", {})
