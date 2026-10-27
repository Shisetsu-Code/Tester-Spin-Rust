"""Actual sanitized BASIC mace probe; preserve geometry, bonus and ledger gates."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from tester_spin.providers.yggdrasil.classic_wild_replacement import ordinary
from tester_spin.providers.yggdrasil import classic_wild_replacement
from tester_spin.providers.yggdrasil.runtime import DemoRuntime, Unsupported, wager_state, collect_request

FIXTURE = Path(__file__).parent/'fixtures/yggdrasil-mace-replacement/captured-basic-mace.json'


class CapturedRuntime(DemoRuntime):
    def __init__(self, fixture):
        super().__init__(None, fixture.get('game_id','captured'), 5, threading.Event(), gate=None)
        self.config = {'ordinary_constraints': fixture['constraints']}
        self.responses = deepcopy(fixture['responses'])
        self.requests = []

    def call(self, operation, body=None, query=None):
        self.requests.append((operation, body))
        return self.responses.pop(0)


class YggdrasilMaceReplacementTests(unittest.TestCase):
    def fixture(self):
        return json.loads(FIXTURE.read_text())

    def event(self, fixture):
        return fixture['responses'][0]['data']['wager']['bets'][0]

    def validate_collect(self, fixture):
        validator = getattr(classic_wild_replacement, 'validate_collect', None)
        self.assertTrue(callable(validator), 'wild-replacement collect validator is missing')
        before, after = map(wager_state, fixture['responses'])
        return validator(before, after, collect_request(before), fixture['constraints'])

    def test_captured_mace_and_spear_collect_receipts_match_the_root_win(self):
        spear = json.loads((FIXTURE.parent.parent/'yggdrasil-round-bindings/classic-wild-replacement.json').read_text())
        for fixture in (self.fixture(), spear):
            with self.subTest(provenance=fixture['provenance']['actions_run']):
                self.assertIsNone(self.validate_collect(fixture))

    def test_collect_wonamount_contradiction_088_to_089_is_rejected(self):
        fixture = self.fixture()
        fixture['responses'][1]['data']['wager']['bets'][0]['wonamount'] = '0.89'
        with self.assertRaisesRegex(ValueError, 'collect settlement mismatch'):
            self.validate_collect(fixture)

    def test_collect_financial_echoes_must_match_the_captured_root(self):
        for mutation in ('exactWon', 'accWa', 'accC', 'coin', 'cashBet', 'currency',
                         'prize_cash', 'prize_net', 'prize_currency', 'prize_aspect', 'missing_prizes'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture()
                bet = fixture['responses'][1]['data']['wager']['bets'][0]
                if mutation == 'exactWon':bet['eventdata']['exactWon'] = '0.89'
                elif mutation == 'accWa':bet['betdata']['accWa'] = '0.89'
                elif mutation == 'accC':bet['betdata']['accC'] = 175
                elif mutation == 'coin':bet['betdata']['coin'] = '0.01'
                elif mutation == 'cashBet':bet['betdata']['cashBet'] = '0.11'
                elif mutation == 'currency':bet['betcurrency'] = 'USD'
                elif mutation == 'prize_cash':bet['prizes'][0]['wonamount'] = '0.89'
                elif mutation == 'prize_net':bet['prizes'][0]['netamount'] = '0.89'
                elif mutation == 'prize_currency':bet['prizes'][0]['woncurrency'] = 'USD'
                elif mutation == 'prize_aspect':bet['prizes'][0]['wonAspect'] = 'BONUS'
                else:bet['prizes'] = None
                with self.assertRaisesRegex(ValueError, 'collect settlement mismatch'):
                    self.validate_collect(fixture)

    def test_collect_validator_does_not_claim_unrecognized_families(self):
        fixture = self.fixture()
        self.event(fixture)['eventdata']['response']['clientData']['featuresUsed'] = ['unknownFeature']
        fixture['responses'][1]['data']['wager']['bets'][0]['wonamount'] = '0.89'
        self.assertIsNone(self.validate_collect(fixture))

    def test_captured_mace_board_is_an_ordinary_modifier(self):
        fixture = self.fixture()
        self.assertEqual(self.event(fixture)['eventdata']['response']['clientData']['featuresUsed'], ['maceFeature'])
        self.assertTrue(ordinary(self.event(fixture), fixture['constraints']))

    def test_captured_round_collects_once_and_reconciles_ledger(self):
        fixture = self.fixture()
        runtime = CapturedRuntime(fixture)
        with tempfile.TemporaryDirectory() as temp:
            result = runtime.round(fixture['template'], Path(temp))
        self.assertEqual(len(runtime.requests), 2)
        self.assertEqual(runtime.requests[1][1]['cmd'], 'C')
        self.assertEqual(runtime.requests[1][1]['amount'], '0')
        self.assertTrue(result['terminal'])
        self.assertTrue(result['known'])
        self.assertTrue(result['base'])

    def test_board_replacements_and_original_icon_must_match(self):
        for mutation in ('wrong_source', 'missing_wild', 'unexplained_change'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture()
                bet = self.event(fixture)
                cd = bet['eventdata']['response']['clientData']
                if mutation == 'wrong_source':cd['wildsAwarded'][0]['icon']['iconEnum'] = 'OTHER'
                elif mutation == 'missing_wild':cd['finalBoard'][0][0] = 'Low1'
                else:cd['finalBoard'][4][2] = 'Wild'
                self.assertFalse(ordinary(bet, fixture['constraints']))

    def test_bonus_or_unobserved_feature_label_stays_unknown(self):
        for mutation in ('bonus_flag', 'other_label', 'mixed_labels', 'bonus_reels'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture()
                bet = self.event(fixture)
                ed = bet['eventdata']
                cd = ed['response']['clientData']
                if mutation == 'bonus_flag':ed['boostData']['gotScatter3AndEnteredFreespins'] = True
                elif mutation == 'other_label':cd['featuresUsed'] = ['unknownFeature']
                elif mutation == 'mixed_labels':cd['featuresUsed'] = ['maceFeature', 'beastFeature']
                else:cd['reelSet'] = 'Bbdeathmatch3Reels2'
                self.assertFalse(ordinary(bet, fixture['constraints']))

    def test_cost_and_award_must_still_match_all_financial_echoes(self):
        for mutation in ('bet_cost', 'cash_win', 'coin_win'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture()
                bet = self.event(fixture)
                if mutation == 'bet_cost':bet['betamount'] = '0.11'
                elif mutation == 'cash_win':bet['eventdata']['response']['cashWin'] = '0.89'
                else:bet['eventdata']['response']['clientData']['wonCoins'] = 175
                self.assertFalse(ordinary(bet, fixture['constraints']))

    def test_runtime_rejects_collect_charge_wager_or_financial_contradiction(self):
        for mutation in ('charge', 'wager', 'wonamount', 'exactWon', 'accWa', 'prize_cash'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture()
                wager = fixture['responses'][1]['data']['wager']
                bet = wager['bets'][0]
                if mutation == 'charge':wager['bets'][0]['betamount'] = '1.00'
                elif mutation == 'wager':wager['wagerid'] = 'different-round'
                elif mutation == 'wonamount':bet['wonamount'] = '0.89'
                elif mutation == 'exactWon':bet['eventdata']['exactWon'] = '0.89'
                elif mutation == 'accWa':bet['betdata']['accWa'] = '0.89'
                else:bet['prizes'][0]['wonamount'] = '0.89'
                runtime = CapturedRuntime(fixture)
                with tempfile.TemporaryDirectory() as temp, self.assertRaises(Unsupported):
                    runtime.round(fixture['template'], Path(temp))


if __name__ == '__main__':
    unittest.main()
