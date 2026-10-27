"""Captured public client excerpts; mutations below are synthetic negatives."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.providers.playtech.primitives import client_contract, discover_modes, entry_command

FIXTURE = ROOT / 'tests/fixtures/playtech-gpas-bindings/compiled-default-cost.json'


class CompiledDefaultCostTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())

    def plan(self, source=None, configuration=None):
        source = source if source is not None else self.fixture['source']
        contract = client_contract(self.fixture['manifest'], [source])
        plan = discover_modes(configuration or self.fixture['configuration'], contract, [source])
        return contract, plan

    def test_captured_default_to_cost_name_to_playmoney_binds_uuid_starting_mode(self):
        contract, plan = self.plan()
        self.assertEqual(plan['unresolved'], [])
        self.assertEqual(plan['modes'][0]['kind'], 'SPIN')
        self.assertEqual(plan['modes'][0]['name'], '5')
        command = entry_command(plan['modes'][0], contract)
        self.assertEqual(command['featureType'], '5')
        self.assertEqual(command['betType'], 'default')
        self.assertEqual(command['betCost'], 5)
        self.assertTrue(plan['domains']['purchase']['complete'])
        self.assertEqual(plan['domains']['purchase']['options'], [])
        self.assertEqual(contract['default_cost_binding']['profile'], 'compiled-default-cost-name/v1')

    def test_unrelated_or_changed_chain_remains_unbound(self):
        source = self.fixture['source']
        mutations = {
            'different decoder property': source.replace('function yGc(n,e){n.b=e}', 'function yGc(n,e){n.z=e}'),
            'different decoder key': source.replace('vFg="name"', 'vFg="unrecognized"'),
            'callback changes selector': source.replace('this.a.S,this.b,null', 'this.a.S,"bonus",null'),
            'no default initialization': source.replace('this.b=oOg,this.a=oOg', 'this.b="bonus",this.a="bonus"'),
            'different current row property': source.replace('t?e=t.b:', 't?e=t.z:'),
        }
        for label, changed in mutations.items():
            with self.subTest(label=label):
                self.assertNotEqual(changed, source)
                contract, plan = self.plan(changed)
                self.assertFalse(contract.get('default_cost_binding'))
                self.assertIn('BASE_MODE_UNBOUND', plan['unresolved'])

    def test_nonunique_or_multi_play_cost_is_not_certified_by_singleton_rule(self):
        for change in ('second_cost', 'multiple_plays', 'unknown_parameter'):
            with self.subTest(change=change):
                configuration = deepcopy(self.fixture['configuration'])
                costs = configuration['game']['costConfiguration']
                if change == 'second_cost':
                    costs.append({**deepcopy(costs[0]), 'name': 'different', 'uuid': 'synthetic-other'})
                elif change == 'multiple_plays':
                    costs[0]['parameters']['startingPlays'] = '10'
                else:
                    costs[0]['parameters']['unlearnedOption'] = 'bonus'
                _, plan = self.plan(configuration=configuration)
                self.assertIn('BASE_MODE_UNBOUND', plan['unresolved'])
                self.assertFalse(plan['domains']['purchase']['complete'])


if __name__ == '__main__':
    unittest.main()
