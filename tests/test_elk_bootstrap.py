"""Observed official ELK page bindings; no network or gameplay in these tests."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.models import Game
from tester_spin.providers.elk import ElkProvider

FIXTURE = ROOT / 'tests/fixtures/elk-bootstrap/official-pages.json'


class FixtureHTTP:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def get(self, url, **options):
        self.requests.append((url, options))
        if url not in self.pages:
            raise AssertionError('Unobserved URL requested')
        class Reply:
            status_code = 200
            is_redirect = False
            def raise_for_status(self):
                pass
        reply = Reply()
        reply.url = url
        reply.text = self.pages[url]
        reply.content = reply.text.encode('utf-8')
        return reply


class ElkBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())

    def helper(self):
        path = ROOT / 'engine/tester_spin/providers/elk_bootstrap.py'
        self.assertTrue(path.is_file(), 'A verified official-page resolver is required')
        return importlib.import_module('tester_spin.providers.elk_bootstrap')

    def extract(self, page=None, game=None, source=None, script_url=None):
        page = page or self.fixture['pages'][0]
        game = game or Game(**page['game'])
        return self.helper().extract_official_demo(game, game.url, page['html'],
            script_url or self.fixture['script_url'],
            source if source is not None else self.fixture['script_excerpt'])

    def test_observed_href_wins_over_conflicting_stale_data_src(self):
        for page, symbol in zip(self.fixture['pages'], ['10256', '10193', '10217']):
            with self.subTest(game=page['game']['slug']):
                binding = self.extract(page)
                self.assertEqual(binding['symbol'], symbol)
                self.assertIn('gameid=' + symbol + '&', binding['client_url'])
                proof = binding['launch_evidence']
                self.assertEqual(proof['source'], page['game']['url'])
                self.assertEqual(proof['profile'], 'elk.official-lightbox-href/v1')
                self.assertEqual(proof['script_sha256'], hashlib.sha256(self.fixture['script_excerpt'].encode()).hexdigest())
                self.assertEqual(proof['page_sha256'], hashlib.sha256(page['html'].encode()).hexdigest())

    def test_changed_handler_or_foreign_script_cannot_resolve_a_launcher(self):
        for source in [self.fixture['script_excerpt'].replace('.prop("href")', '.prop("data-src")'),
                       self.fixture['script_excerpt'].replace('.data("src",b)', '.data("src",unbound)'),
                       self.fixture['script_excerpt'].replace('.attr("href")||', '.attr("data-src")||'),
                       self.fixture['script_excerpt'] + self.fixture['script_excerpt']]:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    self.extract(source=source)
        with self.assertRaises(ValueError):
            self.extract(script_url=self.fixture['script_url'].replace('www.elk-studios.com', 'evil.example'))

    def test_wrong_title_canonical_symbol_or_ambiguous_link_is_rejected(self):
        original = self.fixture['pages'][0]
        changes = [original['html'].replace('<h1>Arcanum</h1>', '<h1>Other Game</h1>'),
                   original['html'].replace('href="https://www.elk-studios.com/games/arcanum/"', 'href="https://www.elk-studios.com/games/other/"'),
                   original['html'].replace('</h3>', '<a class="lightbox-iframe" data-iframe="true" href="https://gamelauncher-stage.contentmedia.eu/1.0/game/?gameid=11111&amp;operatorid=44&amp;mode=demo">Play</a></h3>')]
        for html in changes:
            with self.subTest(html=html):
                self.assertNotEqual(html, original['html'])
                with self.assertRaises(ValueError):
                    self.extract({**original, 'html': html})
        game = Game(**original['game'], symbol='99999')
        with self.assertRaises(ValueError):
            self.extract(game=game)

    def test_demo_authority_mode_and_query_identity_are_explicit(self):
        original = self.fixture['pages'][0]
        for before, after in [('mode=demo', 'mode=real'), ('operatorid=44', 'operatorid=1'),
                              ('gamelauncher-stage.contentmedia.eu', 'evil.example'),
                              ('gameid=10256', 'gameid=10256&amp;gameid=11111')]:
            with self.subTest(change=(before, after)), self.assertRaises(ValueError):
                self.extract({**original, 'html': original['html'].replace(before, after)})

    def test_preparation_binds_fresh_identity_and_metadata_without_gameplay(self):
        page = self.fixture['pages'][0]
        with tempfile.TemporaryDirectory() as temp:
            provider = ElkProvider(Path(temp))
            game = Game(**page['game'])
            metadata = provider.game_dir(game) / 'game.json'
            metadata.write_text(json.dumps({'provider':'elk', 'slug':game.slug,
                                            'client_url':'https://invalid.example/stale'}))
            transport = FixtureHTTP({game.url:page['html'], self.fixture['script_url']:self.fixture['script_excerpt']})
            provider.http = transport
            provider.prepare_test_artifacts(game, timeout_s=5, stop_event=threading.Event(), progress=lambda _:None)
            self.assertEqual(game.symbol, '10256')
            saved = json.loads(metadata.read_text())
            self.assertEqual(saved['symbol'], game.symbol)
            self.assertIn('gameid=10256&', saved['client_url'])
            self.assertEqual(saved['launch_evidence']['source'], game.url)
            self.assertEqual([url for url, _ in transport.requests], [game.url, self.fixture['script_url']])
            self.assertTrue(all(options.get('allow_redirects') is False for _, options in transport.requests))

    def test_failed_refresh_blocks_stale_launch_and_preserves_original_metadata(self):
        page = self.fixture['pages'][0]
        with tempfile.TemporaryDirectory() as temp:
            provider = ElkProvider(Path(temp))
            game = Game(**page['game'])
            metadata = provider.game_dir(game) / 'game.json'
            original = json.dumps({'provider':'elk', 'slug':game.slug,
                'client_url':'https://gamelauncher-stage.contentmedia.eu/1.0/game/?gameid=10256&operatorid=44&mode=demo'})
            metadata.write_text(original)
            provider.http = FixtureHTTP({game.url:page['html'].replace('<h1>Arcanum</h1>', '<h1>Other</h1>')})
            with self.assertRaises(ValueError):
                provider.prepare_test_artifacts(game,timeout_s=5,stop_event=threading.Event(),progress=lambda _:None)
            self.assertEqual(metadata.read_text(), original)
            self.assertEqual(game.symbol, '')
            with patch('tester_spin.providers.elk.requests.Session') as session:
                result = provider.test_game(game,spins=2,timeout_s=5,stop_event=threading.Event(),progress=lambda _:None)
                session.return_value.get.assert_not_called()
                session.return_value.post.assert_not_called()
            self.assertIn('PUBLIC_DEMO_IDENTITY_NOT_CONFIRMED',result.error)
            self.assertEqual(result.successful_spins,0)
            self.assertNotEqual(result.status,'OK')

    def test_redirected_or_foreign_metadata_cannot_prepare(self):
        page = self.fixture['pages'][0]
        for failure in ['redirect', 'metadata']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                provider=ElkProvider(Path(temp));game=Game(**page['game'])
                transport=FixtureHTTP({game.url:page['html']})
                if failure=='redirect':
                    original_get=transport.get
                    def redirect(url,**options):
                        reply=original_get(url,**options);reply.url='https://evil.example/';return reply
                    transport.get=redirect
                else:
                    (provider.game_dir(game)/'game.json').write_text(json.dumps({'provider':'other','slug':game.slug}))
                provider.http=transport
                with self.assertRaises(ValueError):
                    provider.prepare_test_artifacts(game,timeout_s=5,stop_event=threading.Event(),progress=lambda _:None)
                self.assertEqual(game.symbol,'')
                self.assertLessEqual(len(transport.requests),1)

    def test_stop_prevents_static_fetch_and_missing_fresh_preparation_blocks_gameplay(self):
        page=self.fixture['pages'][0]
        with tempfile.TemporaryDirectory() as temp:
            provider=ElkProvider(Path(temp));game=Game(**page['game'])
            provider.http=FixtureHTTP({});stop=threading.Event();stop.set()
            with self.assertRaisesRegex(ValueError,'STOP_REQUESTED'):
                provider.prepare_test_artifacts(game,timeout_s=5,stop_event=stop,progress=lambda _:None)
            self.assertEqual(provider.http.requests,[])
            with patch('tester_spin.providers.elk.requests.Session') as session:
                result=provider.test_game(game,spins=2,timeout_s=5,stop_event=stop,progress=lambda _:None)
                session.return_value.get.assert_not_called()
                session.return_value.post.assert_not_called()
            self.assertIn('STOP_REQUESTED',result.error)


if __name__ == '__main__':
    unittest.main()
