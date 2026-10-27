import hashlib, json, pathlib, sys, tempfile, unittest
from collections import Counter
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.models import GameTestResult, SpinAttempt
from tester_spin.providers.path_coverage import enforce_complete_path_coverage


class PaidInventoryTests(unittest.TestCase):
    def result(self):
        return GameTestResult('playtech', 'demo', 'Demo', 'https://example.test', 1, 1, 0, 'OK')

    def inventory(self, result, options):
        proofs = []
        if result.run_dir:
            raw = pathlib.Path(result.run_dir, 'configuration.raw')
            raw.write_bytes(b'fresh configuration fixture')
            proofs = [{'path':raw.name, 'sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}]
        result.structural_map['paid_option_inventory'] = {
            'schema': 'tester-spin/paid-options/v1',
            'provider': result.provider, 'game': result.slug, 'symbol': result.symbol,
            'primitive': {'id': 'test.contract', 'version': 1},
            'complete': True, 'source': 'fresh client menu and configuration',
            'evidence_files': ['inventory.json'], 'options': options,
            'evidence': proofs,
            'count': len(options), 'counts_by_category': dict(Counter(o['category'] for o in options)),
        }

    def test_missing_inventory_cannot_be_ok(self):
        result = self.result()
        enforce_complete_path_coverage(result)
        self.assertEqual(result.status, 'PARCIAL')

    def test_rule_applies_to_every_provider_not_only_elk_and_playtech(self):
        from tester_spin.providers.registry import PROVIDERS
        for provider in [*PROVIDERS, 'future_provider']:
            with self.subTest(provider=provider):
                result = self.result(); result.provider = provider
                enforce_complete_path_coverage(result)
                self.assertEqual(result.status, 'PARCIAL')

    def test_declaration_from_another_game_cannot_certify_this_game(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result = self.result(); result.run_dir = temp; self.inventory(result, [])
            result.structural_map['paid_option_inventory']['game'] = 'different-game'
            pathlib.Path(temp, 'inventory.json').write_text(json.dumps(result.structural_map['paid_option_inventory']))
            enforce_complete_path_coverage(result)
            self.assertEqual(result.status, 'PARCIAL')

    def test_verified_zero_is_distinct_from_unknown(self):
        result = self.result(); self.inventory(result, [])
        enforce_complete_path_coverage(result)
        self.assertEqual(result.status, 'PARCIAL', 'a nonexistent evidence file is not proof')

    def test_all_paid_categories_require_closed_execution(self):
        result = self.result()
        self.inventory(result, [
            {'id': 'ANTE', 'category': 'ante_bet'},
            {'id': 'BUY', 'category': 'bonus_purchase'},
            {'id': 'SPECIAL', 'category': 'special_mode'},
        ])
        result.attempts = [SpinAttempt(1, True, mode_id='BUY', terminal=True)]
        enforce_complete_path_coverage(result)
        self.assertEqual(result.status, 'PARCIAL')

    def test_dispatched_or_failed_option_does_not_count(self):
        result = self.result(); self.inventory(result, [{'id':'BUY','category':'bonus_purchase'}])
        result.attempts = [SpinAttempt(1, True, mode_id='BUY', terminal=False)]
        enforce_complete_path_coverage(result)
        self.assertEqual(result.status, 'PARCIAL')

    def test_existing_error_is_preserved(self):
        result = self.result(); result.status = 'ERROR'; result.error = 'connection failed'
        enforce_complete_path_coverage(result)
        self.assertEqual(result.status, 'ERROR')
        self.assertIn('connection failed', result.error)

    def test_persisted_complete_inventory_and_all_closed_options_can_pass(self):
        for options in ([], [{'id':'ANTE','category':'ante_bet'}, {'id':'BUY','category':'bonus_purchase'}, {'id':'BOOST','category':'special_mode'}]):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                result = self.result(); result.run_dir = temp; self.inventory(result, options)
                pathlib.Path(temp, 'inventory.json').write_text(json.dumps(result.structural_map['paid_option_inventory']))
                result.attempts = [SpinAttempt(i, True, mode_id=option['id'], terminal=True) for i, option in enumerate(options)]
                enforce_complete_path_coverage(result)
                self.assertEqual(result.status, 'OK', result.error)

    def test_inventory_evidence_must_match_declared_options(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.result(); result.run_dir = temp; self.inventory(result, [])
            pathlib.Path(temp, 'inventory.json').write_text(json.dumps({'complete':True,'source':'menu','options':[{'id':'BUY','category':'bonus_purchase'}]}))
            enforce_complete_path_coverage(result)
            self.assertEqual(result.status, 'PARCIAL')

    def test_modified_underlying_evidence_blocks_ok(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result = self.result(); result.run_dir = temp; self.inventory(result, [])
            pathlib.Path(temp, 'inventory.json').write_text(json.dumps(result.structural_map['paid_option_inventory']))
            pathlib.Path(temp, 'configuration.raw').write_bytes(b'different configuration')
            enforce_complete_path_coverage(result)
            self.assertEqual(result.status, 'PARCIAL')

    def test_declared_count_must_equal_the_enumerated_options(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result=self.result();result.run_dir=temp;self.inventory(result,[])
            result.structural_map['paid_option_inventory']['count']=1
            pathlib.Path(temp,'inventory.json').write_text(json.dumps(result.structural_map['paid_option_inventory']))
            enforce_complete_path_coverage(result)
            self.assertEqual(result.status,'PARCIAL')


if __name__ == '__main__': unittest.main()
