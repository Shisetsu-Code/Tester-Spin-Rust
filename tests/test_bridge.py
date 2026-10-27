import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "engine"))
spec = importlib.util.spec_from_file_location("bridge", ROOT / "engine/bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

from tester_spin.models import Game, GameTestResult
from tester_spin.storage import Storage


class BridgeTests(unittest.TestCase):
    def test_contract_seed_never_changes_source_or_copies_captures(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "evidence") as temp:
            root = Path(temp)
            old, new = root / "source", root / "local"
            (old / "provider/game").mkdir(parents=True)
            original = old / "provider/game/farm-contract.json"
            original.write_text('{"ready": true}', encoding="utf-8")
            (old / "provider/game/private.har").write_text("do not copy", encoding="utf-8")
            class Provider:
                def farm_contract_dir(self, game):
                    return new / "provider/game"
            before = original.stat().st_mtime_ns
            self.assertEqual(bridge.seed_contract(Provider(), None, old, new), 1)
            self.assertEqual((new / "provider/game/farm-contract.json").read_bytes(), original.read_bytes())
            self.assertFalse((new / "provider/game/private.har").exists())
            self.assertEqual(before, original.stat().st_mtime_ns)
            class Escaping:
                def farm_contract_dir(self, game):
                    return old / "provider/game"
            with self.assertRaises(ValueError):
                bridge.seed_contract(Escaping(), None, old, new)

    def run_fixture(self, dry_run=False):
        with tempfile.TemporaryDirectory(dir=ROOT / "evidence") as temp:
            data = Path(temp)
            storage = Storage(data / "tester-spin.sqlite3")
            storage.upsert_games([Game("elk", "fixture", "Fixture", "https://example.com/demo")])
            events = []
            def emit(event, **payload):
                events.append({"event": event, **payload})
            def scheduler(provider, games, **kwargs):
                self.assertEqual([g.slug for g in games], ["fixture"])
                kwargs["on_result"](GameTestResult("elk", "fixture", "Fixture", "https://example.com/demo", 1, 1, 0, "OK"))
            with patch.object(bridge, "DATA", data), patch.object(bridge, "emit", emit), patch.object(bridge, "seed_contract"), patch("tester_spin.providers.registry.create_provider", return_value=object()), patch("tester_spin.scheduler.run_game_tests", side_effect=scheduler) as run:
                bridge.Bridge().execute({"cmd": "run", "provider": "elk", "slugs": ["fixture"], "dry_run": dry_run})
            if dry_run:
                run.assert_not_called()
                self.assertTrue(any(e["event"] == "plan" and e["executed"] is False for e in events))
            else:
                self.assertEqual(storage.get_game("elk", "fixture").last_status, "OK")
                self.assertTrue(any(e["event"] == "result" and e["status"] == "OK" for e in events))
            self.assertEqual(events[-1]["event"], "done")

    def test_dry_run_does_not_execute_games(self):
        self.run_fixture(dry_run=True)

    def test_result_is_persisted_in_local_database_and_streamed(self):
        self.run_fixture()

    def test_stop_sets_event_without_killing_or_replaying(self):
        instance = bridge.Bridge()
        with patch.object(bridge, "emit"):
            self.assertTrue(instance.dispatch({"cmd": "stop"}))
            self.assertTrue(instance.stop.is_set())

    def test_catalog_adapter_without_timeout_parameter_is_supported(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'evidence') as temp:
            events = []
            class Provider:
                def crawl_catalog(self, *, stop_event, progress, max_pages, on_game=None):
                    return [Game('elk', 'fixture', 'Fixture', 'https://example.com/demo')]
            with patch.object(bridge, 'DATA', Path(temp)), patch.object(bridge, 'emit', side_effect=lambda event, **payload: events.append({'event': event, **payload})), patch('tester_spin.providers.registry.create_provider', return_value=Provider()):
                bridge.Bridge().execute({'cmd': 'catalog', 'provider': 'elk', 'timeout': 20})
            self.assertFalse(any(e['event'] == 'error' for e in events), events)
            self.assertTrue(any(e['event'] == 'done' and e.get('count') == 1 for e in events), events)


if __name__ == "__main__":
    unittest.main()
