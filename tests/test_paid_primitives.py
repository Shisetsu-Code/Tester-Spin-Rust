import json, pathlib, sys, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
from tester_spin.models import GameTestResult


class PaidPrimitivesTests(unittest.TestCase):
    def declaration(self, name, unknown=False):
        from tester_spin.providers.playtech.primitives import paid_option_declaration
        plan = {'modes': [
            {'id':'base','name':'default','kind':'SPIN','cost':1,'multiplier':1},
            {'id':'buy','name':name,'kind':'PURCHASE','cost':100,'multiplier':1},
            {'id':'ante','name':'extra','kind':'ANTE_BET','cost':2,'multiplier':1},
            {'id':'other','name':'unbound','kind':'UNKNOWN_FEATURE' if unknown else 'FEATURE_SPIN','cost':5,'multiplier':1}],
            'unresolved': ['UNBOUND_STAKE_MODE:unbound'] if unknown else []}
        return paid_option_declaration(plan)

    def test_one_primitive_handles_different_game_option_names(self):
        for name in ['BuyFeature', 'BuyFeature2Pot', 'another-name']:
            declaration = self.declaration(name)
            self.assertTrue(declaration['complete'])
            self.assertEqual(len(declaration['options']), 3)
            self.assertEqual({o['category'] for o in declaration['options']}, {'bonus_purchase','ante_bet','special_mode'})

    def test_unbound_option_is_retained_and_blocks_completeness(self):
        declaration = self.declaration('BuyFeature', unknown=True)
        self.assertFalse(declaration['complete'])
        self.assertIn('other', [o['id'] for o in declaration['options']])

    def test_evidence_writer_binds_primitive_to_current_game(self):
        from tester_spin.paid_options import write_paid_option_inventory
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result = GameTestResult('playtech','some-game','Some game','https://example.test',1,0,0,'PARCIAL',run_dir=temp)
            pathlib.Path(temp,'bootstrap.json').write_text('{"fresh":true}')
            inventory = write_paid_option_inventory(result, **self.declaration('BuyFeature'), evidence_files=['bootstrap.json'])
            saved = json.loads(pathlib.Path(temp,'paid-option-inventory.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['game'], result.slug)
            self.assertEqual(saved['primitive'], inventory['primitive'])
            self.assertEqual(saved['count'], 3)

    def test_missing_raw_evidence_cannot_produce_complete_declaration(self):
        from tester_spin.paid_options import write_paid_option_inventory
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result = GameTestResult('playtech','demo','Demo','https://example.test',1,0,0,'OK',run_dir=temp)
            inventory = write_paid_option_inventory(result, **self.declaration('BuyFeature'), evidence_files=['missing.json'])
            self.assertFalse(inventory['complete'])
            self.assertIsNone(inventory['count'])

    def test_no_primitive_is_explicit_unknown_not_zero(self):
        from tester_spin.paid_options import ensure_paid_option_declaration
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result = GameTestResult('future_provider','demo','Demo','https://example.test',1,0,0,'OK',run_dir=temp)
            ensure_paid_option_declaration(result)
            declaration = result.structural_map['paid_option_inventory']
            self.assertFalse(declaration['complete'])
            self.assertIsNone(declaration['count'])
            self.assertEqual(declaration['state'], 'UNKNOWN')

    def test_one_unrecognized_cost_is_not_assumed_to_mean_zero_paid_options(self):
        from tester_spin.providers.playtech.primitives import discover_modes, paid_option_declaration
        plan = discover_modes({'game':{'costConfiguration':[{'uuid':'mystery','name':'MysteryPaidAction','cost':100}], 'baseCostMultipliers':[1]}},
                              {'dialect':'legacy'}, [])
        declaration = paid_option_declaration(plan)
        self.assertFalse(declaration['complete'])
        self.assertEqual(declaration['options'][0]['id'], 'mystery')


if __name__ == '__main__': unittest.main()
