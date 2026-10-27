"""Real adapter with synthetic, externally controlled demo transport; no network."""
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
from tester_spin.models import Game
from tester_spin.providers.hacksaw.adapter import HacksawProvider


class SyntheticResponse:
    def __init__(self, data=None, text=None):
        self.data = data
        self.text = json.dumps(data) if text is None else text

    def json(self):
        return copy.deepcopy(self.data)

    def raise_for_status(self):
        pass


class SyntheticHacksawTransport:
    """Author ledger-balanced replies with explicit unique rounds and menus."""
    def __init__(self, *, choices=(), failure=None, only_purchase=False, menus=()):
        self.balance = 100000
        self.choices = list(choices)
        self.menus = [list(menu) for menu in menus]
        self.pending_menu = []
        self.failure = failure
        self.roots = []
        self.actions = []
        self.requests = []
        self.pending = None
        self.sequence = 1
        self.factors = {'paid': 3} if only_purchase else {'paid': 3, 'mod_paid': 2}

    def get(self, url, **kwargs):
        if url.endswith('/version.json'):
            return SyntheticResponse({'version': '9.8.7'})
        if url.endswith('/main.js'):
            return SyntheticResponse(text='/* synthetic: explicit item types come from init */')
        raise AssertionError('Unexpected GET: '+url)

    def response(self, round_id, status, actions, *, win=0, total_win=0):
        return SyntheticResponse({'statusCode': 0,
            'accountBalance': {'currencyCode': 'EUR', 'balance': str(self.balance)},
            'round': {'roundId': round_id, 'status': status, 'possibleActions': actions,
                      'events': [{'ba': '0', 'bc': '0', 'wc': '0', 'awc': '0',
                                  'wa': str(win), 'awa': str(total_win)}]}})

    def post(self, url, *, json, **kwargs):
        if url.endswith('/play/authenticate'):
            bonuses = [{'bonusGameId': selector, 'betCostMultiplier': factor,
                        'featureBuyItemType': 'FeatureSpinItem' if selector.startswith('mod_') else 'BonusBuyItem'}
                       for selector, factor in self.factors.items()]
            return SyntheticResponse({'statusCode': 0, 'sessionUuid': 'synthetic-session',
                'betLevels': ['10'], 'roundStatus': 'completed', 'minimumRoundDuration': 0,
                'accountBalance': {'currencyCode': 'EUR', 'balance': str(self.balance)}, 'bonusGames': bonuses})
        if not url.endswith('/play/bet'):
            raise AssertionError('Unexpected POST: '+url)
        self.requests.append(copy.deepcopy(json))
        if json['seq'] <= self.sequence:
            raise AssertionError('Sequence must advance')
        self.sequence = json['seq']
        if 'bets' in json:
            if self.pending is not None:
                raise AssertionError('New paid root while previous round is unresolved')
            bet = json['bets'][0]
            selector = bet.get('buyBonus', 'SPIN')
            self.roots.append(selector)
            round_id = f'synthetic-round-{len(self.roots)}'
            self.balance -= int(bet['betAmount']) * self.factors.get(selector, 1)
            if self.failure == 'ledger':
                self.balance += 1
                return self.response(round_id, 'completed', [])
            if self.failure == 'pending':
                self.pending = round_id
                return self.response(round_id, 'started', [])
            if self.failure == 'transport':
                self.pending = round_id
                raise TimeoutError('synthetic uncertain dispatch')
            if selector == 'paid' and (self.choices or self.menus):
                self.pending = round_id
                number = self.roots.count('paid') - 1
                self.pending_menu = self.menus[min(number, len(self.menus)-1)] if self.menus else self.choices
                return self.response(round_id, 'started', self.pending_menu)
            self.balance += 3
            return self.response(round_id, 'completed', [], win=3, total_win=3)
        if json['roundId'] != self.pending:
            raise AssertionError('Continuation changed round')
        action = json['continueInstructions']['action']
        if action not in self.pending_menu:
            raise AssertionError('Undeclared choice')
        self.actions.append(action)
        if self.failure == 'choice-ledger':
            self.balance += 4
            return self.response(self.pending, 'completed', [], win=3, total_win=3)
        if self.failure == 'choice-pending':
            return self.response(self.pending, 'started', [])
        self.balance += 3
        round_id = self.pending
        self.pending = None
        return self.response(round_id, 'completed', [], win=3, total_win=3)


class HacksawSamplingTests(unittest.TestCase):
    def run_adapter(self, transport, *, spins=2):
        with tempfile.TemporaryDirectory() as temp:
            provider = HacksawProvider(Path(temp))
            provider.http.close()
            provider.http = transport
            game = Game('hacksaw', '999001', 'Synthetic protocol fixture',
                        'https://www.hacksawgaming.com/games/slots#game-999001', symbol='999001')
            return provider.test_game(game, spins=spins, timeout_s=1,
                                      stop_event=threading.Event(), progress=lambda message: None)

    def test_two_samples_of_base_and_every_paid_root_before_return(self):
        transport = SyntheticHacksawTransport()
        result = self.run_adapter(transport)
        self.assertEqual(result.status, 'OK', result.error)
        self.assertEqual(Counter(a.mode_id for a in result.attempts),
                         {'SPIN': 2, 'BUY_paid': 2, 'BUY_mod_paid': 2})
        self.assertTrue(all(a.ok and a.terminal for a in result.attempts))
        self.assertEqual(Counter(transport.roots), {'SPIN': 4, 'paid': 2, 'mod_paid': 2})
        for mode in result.discovered_modes:
            self.assertEqual(mode['required_samples'], 2)
            self.assertTrue(all(count >= 2 for count in mode['sample_counts'].values()))

    def test_each_announced_choice_gets_two_closed_samples_without_overbuying(self):
        transport = SyntheticHacksawTransport(choices=['left', 'right'], only_purchase=True)
        result = self.run_adapter(transport)
        self.assertEqual(result.status, 'OK', result.error)
        self.assertEqual(Counter(transport.actions), {'left': 2, 'right': 2})
        self.assertEqual(Counter(transport.roots), {'SPIN': 4, 'paid': 4})
        choice = next(m for m in result.discovered_modes if m['kind'] == 'CHOICE_CONTINUATION')
        self.assertEqual(choice['sample_counts'], {'left': 2, 'right': 2})
        self.assertEqual(choice['required_samples'], 2)
        self.assertTrue(choice['validated'])

    def test_newly_announced_menu_option_keeps_its_own_sample_deficit(self):
        transport = SyntheticHacksawTransport(only_purchase=True,
            menus=[['left'], ['right'], ['left', 'right']])
        result = self.run_adapter(transport)
        self.assertEqual(result.status, 'OK', result.error)
        self.assertEqual(Counter(transport.actions), {'left': 2, 'right': 2})
        self.assertEqual(transport.roots.count('paid'), 4)

    def test_exploration_budget_leaves_missing_samples_partial(self):
        transport = SyntheticHacksawTransport(choices=[f'option_{i}' for i in range(16)], only_purchase=True)
        result = self.run_adapter(transport, spins=3)
        self.assertEqual(result.status, 'PARCIAL')
        self.assertEqual(transport.roots.count('paid'), 35)  # Three scheduled plus 32 bounded probes.
        choice = next(m for m in result.discovered_modes if m['kind'] == 'CHOICE_CONTINUATION')
        self.assertFalse(choice['validated'])
        self.assertTrue(any(choice['sample_counts'].get(option, 0) < 3 for option in choice['required_options']))
        self.assertNotIn('hacksaw_return', result.structural_map)

    def test_oversized_menu_stops_before_any_undeclared_exploration(self):
        transport = SyntheticHacksawTransport(choices=[f'option_{i}' for i in range(17)], only_purchase=True)
        result = self.run_adapter(transport)
        self.assertEqual(result.status, 'PARCIAL')
        self.assertEqual(transport.roots, ['SPIN', 'SPIN', 'paid'])
        self.assertEqual(transport.actions, [])
        self.assertNotIn('hacksaw_return', result.structural_map)

    def test_no_second_dispatch_after_first_unsettled_or_invalid_root(self):
        for failure in ['ledger', 'pending', 'transport']:
            with self.subTest(failure=failure):
                transport = SyntheticHacksawTransport(failure=failure)
                result = self.run_adapter(transport)
                self.assertNotEqual(result.status, 'OK')
                self.assertEqual(len(transport.requests), 1)
                self.assertEqual(len(result.attempts), 1)
                self.assertFalse(result.attempts[0].ok)
                self.assertNotIn('hacksaw_return', result.structural_map)

    def test_no_new_purchase_or_return_after_bad_choice_settlement(self):
        for failure in ['choice-ledger', 'choice-pending']:
            with self.subTest(failure=failure):
                transport = SyntheticHacksawTransport(choices=['left', 'right'], failure=failure, only_purchase=True)
                result = self.run_adapter(transport)
                self.assertNotEqual(result.status, 'OK')
                self.assertEqual(transport.roots, ['SPIN', 'SPIN', 'paid'])
                self.assertEqual(transport.actions, ['left'])
                self.assertNotIn('hacksaw_return', result.structural_map)


if __name__ == '__main__':
    unittest.main()
