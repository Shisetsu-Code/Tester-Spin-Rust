import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.models import Game
from tester_spin.storage import Storage


class CatalogSelectionTests(unittest.TestCase):
    def helper(self):
        path = ROOT / 'scripts/ci_catalog.py'
        self.assertTrue(path.is_file(), 'The bounded catalog helper must exist')
        spec = importlib.util.spec_from_file_location('ci_catalog', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def game(self, slug):
        return Game('fixture', slug, slug.title(), 'https://example.test/' + slug)

    def test_callback_checkpoints_distinct_selection_before_cooperative_stop(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'selected-games.json'
            rows = [self.game('one'), self.game('one'), self.game('two'), self.game('three')]
            class Provider:
                key = 'fixture'
                def crawl_catalog(self, *, stop_event, progress, max_pages, on_game):
                    for row in rows:
                        on_game(row)
                        saved = json.loads(output.read_text())
                        assert saved['selected'] >= 1
                    assert stop_event.is_set()
                    return []
            report = helper.collect_catalog(Provider(), root / 'data', output, limit=3)
            self.assertEqual([g['slug'] for g in report['games']], ['one', 'two', 'three'])
            self.assertEqual(len(Storage(root / 'data/tester-spin.sqlite3').list_games('fixture')), 3)

    def test_no_callback_uses_returned_games_and_limits_persistence(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [self.game(str(i)) for i in range(5)]
            class Provider:
                key = 'fixture'
                def crawl_catalog(self, *, stop_event, progress, max_pages):
                    return rows
            report = helper.collect_catalog(Provider(), root / 'data', root / 'selected-games.json', limit=3)
            self.assertEqual(report['selected'], 3)
            self.assertEqual(len(Storage(root / 'data/tester-spin.sqlite3').list_games('fixture')), 3)

    def test_atomic_paged_catalog_can_finish_before_emitting_selected_games(self):
        helper = self.helper()
        rows = [self.game(str(i)) for i in range(5)]
        class Provider:
            key = 'fixture'
            def crawl_catalog(self, *, stop_event, progress, max_pages, on_game):
                # RubyPlay's REST contract validates all pages before callbacks.
                if max_pages < 2:
                    raise ValueError('Pagination limited before any records can be emitted')
                for row in rows:
                    on_game(row)
                return rows
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = helper.collect_catalog(Provider(), root / 'data', root / 'selected-games.json', limit=3)
            self.assertEqual(report['selected'], 3)
            self.assertEqual(report['error'], '')

    def test_interruption_retains_samples_and_unexpected_error_is_sanitized(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = self.game('one')
            class Interrupted:
                key = 'fixture'
                def crawl_catalog(self, *, stop_event, progress, max_pages, on_game):
                    on_game(game)
                    raise InterruptedError('cancelled')
            report = helper.collect_catalog(Interrupted(), root / 'data', root / 'selected-games.json', limit=3)
            self.assertEqual(report['selected'], 1)
            class Broken:
                key = 'fixture'
                def crawl_catalog(self, **kwargs):
                    raise RuntimeError('token=supersecret')
            output = root / 'empty.json'
            report = helper.collect_catalog(Broken(), root / 'empty-data', output, limit=3)
            self.assertEqual(report['selected'], 0)
            self.assertEqual(report['error'], 'CATALOG_FAILURE: RuntimeError')
            self.assertNotIn('supersecret', output.read_text())


if __name__ == '__main__':
    unittest.main()
