"""Synthetic GPAS line-stake fixtures; not claimed as captured game sessions."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.providers.playtech.primitives import discover_modes, entry_command


class PlaytechLineStakeTests(unittest.TestCase):
    def configuration(self):
        return {'game': {'baseCostMultipliers': [1, 2], 'costConfiguration': [
            {'name': '10', 'uuid': 'synthetic-ten-lines', 'cost': 10,
             'parameters': {'startingMode': 'Standard', 'startingPlays': '1', 'winline': '10',
                            'discountable': 'false', 'evalPayout': 'LEFT_TO_RIGHT',
                            'maxBaseCostMultiplier': '100000'}}]}}

    def contract(self):
        return {'dialect': 'modern', 'class': 'synthetic.Command', 'entry_id': 40021,
                'standard_start_bound': False, 'base_selector': None, 'adapter_maps': {}}

    def test_single_line_stake_uses_same_explicit_client_binding_as_line_domain(self):
        source = 'winline stakeCostUuid stakeCostName GLU.game.playMoney'
        plan = discover_modes(self.configuration(), self.contract(), [source])
        self.assertEqual(plan['unresolved'], [])
        mode = plan['modes'][0]
        self.assertEqual(mode['kind'], 'SPIN')
        command = entry_command(mode, self.contract())
        self.assertEqual(command['featureType'], '10')
        self.assertEqual(command['betCost'], 10)
        self.assertEqual(plan['domains']['purchase']['options'], [])
        self.assertTrue(plan['domains']['purchase']['complete'])

    def test_single_numeric_cost_without_client_line_binding_remains_unknown(self):
        plan = discover_modes(self.configuration(), self.contract(), ['unrecognized client'])
        self.assertEqual(plan['modes'][0]['kind'], 'UNKNOWN_FEATURE')
        self.assertIn('BASE_MODE_UNBOUND', plan['unresolved'])
        self.assertFalse(plan['domains']['purchase']['complete'])

    def test_mismatched_winline_or_nonstandard_start_remains_unknown(self):
        for field, value in [('winline', '5'), ('startingMode', 'Bonus')]:
            with self.subTest(field=field):
                configuration = deepcopy(self.configuration())
                configuration['game']['costConfiguration'][0]['parameters'][field] = value
                plan = discover_modes(configuration, self.contract(),
                                      ['winline stakeCostUuid stakeCostName GLU.game.playMoney'])
                self.assertEqual(plan['modes'][0]['kind'], 'UNKNOWN_FEATURE')
                self.assertIn('BASE_MODE_UNBOUND', plan['unresolved'])


if __name__ == '__main__':
    unittest.main()
