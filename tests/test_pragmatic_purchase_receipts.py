"""Synthetic receipts for the no-bl echo shape observed in Actions 40544934511.

These are controlled protocol fixtures, not complete captured live sessions.
"""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from tester_spin.models import GameTestResult, SpinAttempt
from tester_spin.providers.pragmatic_declared_coverage import verified_mode_ids


class PragmaticPurchaseReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mode = dict(id='PURCHASE_1', kind='PURCHASE', enabled=True, price_known=True,
                         provider_bl=0, provider_pur=0, paid_cost=400.0, price_x_base=200.0)
        self.request = dict(action='doSpin', symbol='synthetic', bl='0', pur='0', c='0.08', l='25')
        # Chests' receipt echoes coin/lines and purchase selectors, but omits bl.
        self.response = dict(c='0.08', l='25', purtr='1', puri='0', na='s')

    def result(self, *, response=None, request=None, mode=None, terminal=True, samples=2):
        result = GameTestResult('pragmatic', 'synthetic', 'Synthetic', '', 2, 2, 0, 'OK',
                                symbol='synthetic', run_dir=str(self.root),
                                discovered_modes=[mode or self.mode], samples_per_path=samples)
        for number in range(2):
            directory = self.root / ('attempt-' + str(number))
            directory.mkdir(exist_ok=True)
            (directory/'step-000-entry.request.txt').write_text(urlencode(request or self.request))
            (directory/'step-000-entry.response.json').write_text(json.dumps(self.response if response is None else response))
            (directory/'step-000-entry.http.json').write_text(json.dumps({'status': 200}))
            (directory/'return-to-base.json').write_text(json.dumps({'status': 'CONFIRMED', 'consecutive_base': 2}))
            result.attempts.append(SpinAttempt(number+1, True, mode_id=(mode or self.mode)['id'],
                mode_kind=(mode or self.mode)['kind'], terminal=terminal, artifact_dir=str(directory)))
        return result

    def test_coin_line_purchase_receipt_without_bl_is_bound_to_base_selector(self):
        self.assertEqual(verified_mode_ids(self.result()), {'PURCHASE_1'})

    def test_wrong_echoed_bl_or_wrong_purchase_selector_stays_unverified(self):
        for change in [{'bl': '1'}, {'puri': '1'}, {'purtr': '0'}, {'c': '0.10'}, {'l': '20'}]:
            with self.subTest(change=change):
                self.assertEqual(verified_mode_ids(self.result(response=dict(self.response, **change))), set())

    def test_missing_or_nonfinite_quote_echo_is_not_a_bound_receipt(self):
        for field in ['c', 'l']:
            for value in [None, '', 'NaN', '-1', '0']:
                with self.subTest(field=field, value=value):
                    response = dict(self.response)
                    if value is None:
                        response.pop(field)
                    else:
                        response[field] = value
                    self.assertEqual(verified_mode_ids(self.result(response=response)), set())

    def test_no_bl_receipt_does_not_certify_nonbase_ante(self):
        mode = dict(self.mode, id='ANTE_BET_1', kind='ANTE_BET', provider_bl=1, provider_pur=None)
        request = dict(self.request, bl='1')
        request.pop('pur')
        self.assertEqual(verified_mode_ids(self.result(mode=mode, request=request)), set())

    def test_terminal_sample_count_and_quote_cost_remain_required(self):
        self.assertEqual(verified_mode_ids(self.result(terminal=False)), set())
        self.assertEqual(verified_mode_ids(self.result(samples=3)), set())
        for cost in [399.0, True, float('inf')]:
            with self.subTest(cost=cost):
                self.assertEqual(verified_mode_ids(self.result(mode=dict(self.mode, paid_cost=cost))), set())

    def test_legacy_bl_echo_remains_supported(self):
        self.assertEqual(verified_mode_ids(self.result(response=dict(self.response, bl='0'))), {'PURCHASE_1'})


if __name__ == '__main__':
    unittest.main()
