"""Replay captured, sanitized response subtrees; never call a live backend."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.providers.yggdrasil.runtime import DemoRuntime, Unsupported
from tester_spin.return_to_base import verify_return_to_base

FIXTURES = ROOT / 'tests/fixtures/yggdrasil-round-bindings'


class CapturedRuntime(DemoRuntime):
    def __init__(self, fixture):
        super().__init__(None, fixture.get('game_id','captured'), 5, threading.Event(), gate=None)
        self.config = {'ordinary_constraints': fixture['constraints']}
        self.responses = deepcopy(fixture['responses'])
        self.requests = []

    def call(self, operation, body=None, query=None):
        self.requests.append((operation, body))
        return self.responses.pop(0)


class YggdrasilRoundBindingTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((FIXTURES / (name + '.json')).read_text())

    def replay(self, fixture):
        runtime = CapturedRuntime(fixture)
        with tempfile.TemporaryDirectory() as temp:
            result = runtime.round(fixture['template'], Path(temp))
        self.assertEqual(len(runtime.requests), 2, 'Exactly root and authorized C; no wager retry')
        self.assertEqual(runtime.requests[-1][1]['cmd'], 'C')
        self.assertEqual(runtime.requests[-1][1]['amount'], '0')
        return result

    def test_captured_classic_wild_replacements_are_a_proven_base_modifier(self):
        result = self.replay(self.fixture('classic-wild-replacement'))
        self.assertTrue(result['terminal'])
        self.assertTrue(result['known'])
        self.assertTrue(result['base'])

    def test_classic_bonus_flag_or_unexplained_board_change_stays_unknown(self):
        for mutation in ('bonus_flag', 'unexplained_board', 'cash_mismatch'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture('classic-wild-replacement')
                event = fixture['responses'][0]['data']['wager']['bets'][0]['eventdata']
                if mutation == 'bonus_flag':
                    event['boostData']['gotScatter3AndEnteredFreespins'] = True
                elif mutation == 'unexplained_board':
                    event['response']['clientData']['finalBoard'][0][0] = 'Wild'
                else:
                    event['response']['cashWin'] = '999.00'
                self.assertFalse(self.replay(fixture)['known'])

    def test_captured_named_cascade_removes_its_previously_created_multiplier_symbol(self):
        result = self.replay(self.fixture('named-multiplier-removal'))
        self.assertTrue(result['known'])
        self.assertTrue(result['base'])
        self.assertTrue(result['terminal'])

    def test_unbound_or_changed_removed_multiplier_stays_unknown(self):
        for mutation in ('different_multiplier', 'different_symbol', 'absent_creation', 'overwritten_creation'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture('named-multiplier-removal')
                actions = fixture['responses'][0]['data']['wager']['bets'][0]['eventdata']['response']['clientData']['actions']
                removed = next(s for a in actions if a.get('operation') == 'remove' for s in a['symbols'] if 'multiplier' in s)
                if mutation == 'different_multiplier':
                    removed['multiplier'] = 99
                elif mutation == 'different_symbol':
                    removed['name'] = 'UNBOUND'
                elif mutation == 'absent_creation':
                    actions[:] = [a for a in actions if a.get('operation') != 'create']
                else:
                    index = next(i for i,a in enumerate(actions) if a.get('operation') == 'remove' and any('multiplier' in s for s in a['symbols']))
                    actions.insert(index, {'name':'operateSymbols', 'operation':'create', 'symbols':[
                        {'position':deepcopy(removed['position']), 'name':'OTHER', 'subsymbol':False}]})
                self.assertFalse(self.replay(fixture)['known'])

    def test_captured_automatic_bonus_is_known_feature_and_never_counts_as_base(self):
        result = self.replay(self.fixture('typed-automatic-bonus'))
        self.assertTrue(result['terminal'])
        self.assertTrue(result['known'])
        self.assertFalse(result['base'])
        with tempfile.TemporaryDirectory() as temp:
            outcomes = iter([result, {'ok': True, 'known': True, 'base': True},
                             {'ok': True, 'known': True, 'base': True}])
            proof = verify_return_to_base(Path(temp), lambda _: next(outcomes))
        self.assertEqual(proof['status'], 'CONFIRMED')
        self.assertEqual(len(proof['probes']), 3)
        self.assertEqual(proof['consecutive_base'], 2)

    def test_incomplete_or_unknown_typed_bonus_stays_unknown(self):
        for mutation in ('remaining_spins', 'missing_exit', 'unknown_action', 'wrong_win'):
            with self.subTest(mutation=mutation):
                fixture = self.fixture('typed-automatic-bonus')
                actions = fixture['responses'][0]['data']['wager']['bets'][0]['eventdata']['response']['clientData']['actions']
                if mutation == 'remaining_spins':
                    next(a for a in reversed(actions) if a.get('name') == 'spinsLeft')['value'] = 1
                elif mutation == 'missing_exit':
                    actions[:] = [a for a in actions if a.get('featureIdentifier') != 'exitBonusGame']
                elif mutation == 'unknown_action':
                    actions.insert(-1, {'$type': 'ActionGame_UnlearnedDecision'})
                else:
                    actions[-1]['modeWin']['amount'] = 999
                self.assertFalse(self.replay(fixture)['known'])

    def test_capture_preserves_the_recognized_response_fields(self):
        fixture = self.fixture('typed-automatic-bonus')
        runtime = CapturedRuntime(fixture)
        with tempfile.TemporaryDirectory() as temp:
            runtime.round(fixture['template'], Path(temp))
            saved = json.loads((Path(temp) / 'step-001-response.json').read_text())
        captured = fixture['responses'][0]['data']['wager']['bets'][0]['eventdata']['response']['clientData']
        self.assertEqual(saved['bets'][0]['clientData'], captured)

    def test_wrong_wager_or_extra_collect_charge_never_establishes_a_round(self):
        for name in ('classic-wild-replacement', 'named-multiplier-removal', 'typed-automatic-bonus'):
            for mutation in ('wager', 'charge'):
                with self.subTest(family=name, mutation=mutation):
                    fixture = self.fixture(name)
                    reply = fixture['responses'][1]['data']['wager']
                    if mutation == 'wager':
                        reply['wagerid'] = 'different-round'
                    else:
                        reply['bets'][0]['betamount'] = '1.00'
                    runtime = CapturedRuntime(fixture)
                    with tempfile.TemporaryDirectory() as temp, self.assertRaises(Unsupported):
                        runtime.round(fixture['template'], Path(temp))


if __name__ == '__main__':
    unittest.main()
