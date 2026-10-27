"""Real D1 execution against a synthetic WebSocket; no captured/live sessions.

Only bootstrap discovery and socket creation are injected. The adapter's wire
serializer, receiver, quote/debit checks and actual return checker all run.
"""
from collections import deque
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
sys.path.insert(0, str(ROOT/'tests'))
from test_d1_paid_domains import BASE
from tester_spin.models import Game
from tester_spin.providers.one_spin4win import OneSpin4WinProvider
from tester_spin.providers.one_spin4win_purchases import discover_paid_contract
from tester_spin.return_to_base import audit_scope


CLIENT = BASE + '''var SyntheticCashView=function(){BasicSlotView.call(this);
this.sideBet=1;this.sideBetPercent=.5;this.halfLines=!0;this.allWays=!1;
this.forBetLinesDivider=1;};$jscomp.inherits(SyntheticCashView,BasicSlotView);'''
INITIAL = {'type': 1, 'g': 700, 'bs': '121112', 'b3': 0, 'l': 40,
           'b1': 20, 'b2': 5000, 'b': 10000, 'w': 0, 'bf': 'f'}


def ordinary(balance, win=0, *, game_number=701):
    return {'type': 3, 'g': game_number, 'st': 3, 'b': balance, 'w': win, 'l': 40, 'b3': 0}


def bonus(balance=9970):
    return {'type': 3, 'g': 701, 'st': 5, 'b': balance, 'w': 0,
            'b8': 0, 'b9': 2, 'l': 40, 'b3': 0}


class SyntheticWebSocket:
    def __init__(self, replies):
        self.replies = deque(copy.deepcopy(replies))
        self.sent = []
        self.closed = False

    def send(self, wire):
        if not isinstance(wire, str) or not wire.startswith('A/u2'):
            raise AssertionError('Unexpected synthetic socket protocol')
        self.sent.append(json.loads(wire[4:]))

    def recv(self):
        if not self.replies:
            raise AssertionError('Unexpected receive after synthetic script exhausted')
        return json.dumps(self.replies.popleft())

    def close(self):
        self.closed = True

    @property
    def plays(self):
        return [message for message in self.sent if message['type'] == '1']


class D1AnteExecutionTests(unittest.TestCase):
    def execute(self, socket, directory):
        contract = discover_paid_contract([CLIENT], 'SyntheticCash')
        self.assertEqual(contract['feature_domains']['ante']['options'], ['D1_ANTE_BET'])
        spec = dict(paid_client_contract=contract, game_name='SyntheticCash', version='264',
                    wallet='EUR', currency='EUR', ws_url='wss://synthetic.invalid/demo')
        provider = object.__new__(OneSpin4WinProvider)
        provider._discover_runtime_spec = lambda game, **kwargs: copy.deepcopy(spec)
        provider._open_websocket = lambda runtime, timeout_s: socket
        game = Game('1spin4win', 'synthetic-cash', 'Synthetic ante fixture', 'https://example.invalid/demo')
        with audit_scope():
            return provider._execute_direct_ws_spin(game, timeout_s=1, attempt_dir=directory,
                                                   feature_selector=1, feature_kind='ANTE_BET')

    def test_ante_30_then_two_base_20_probes_reconcile_actual_credits(self):
        socket = SyntheticWebSocket([INITIAL, ordinary(9975, 5),
            ordinary(9959, 4, game_number=702), ordinary(9939, 0, game_number=703)])
        with tempfile.TemporaryDirectory() as temp:
            ok, terminal, _, _, _, warning = self.execute(socket, Path(temp))
        self.assertTrue(ok)
        self.assertTrue(terminal, warning)
        self.assertEqual(warning, '')
        self.assertEqual([message['data'] for message in socket.plays],
                         ['40,0,0,1', '40,0,0', '40,0,0'])
        self.assertTrue(socket.closed)

    def test_false_first_debit_rejects_before_continuation_or_return(self):
        # Would mean a 20-unit debit, while the declared ante quote is 30.
        socket = SyntheticWebSocket([INITIAL, ordinary(9985, 5), ordinary(9965)])
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'D1_ANTE_DEBIT_OR_WIN_MISMATCH'):
                self.execute(socket, Path(temp))
        self.assertEqual(len(socket.plays), 1)
        self.assertEqual(len(socket.replies), 1)
        self.assertTrue(socket.closed)

    def test_ante_entering_bonus_stops_before_unbound_continuation(self):
        garbage = {'type': 3, 'g': 701, 'st': 12, 'b8': 2, 'b9': 2, 'b': 123, 'w': 100}
        socket = SyntheticWebSocket([INITIAL, bonus(), garbage, ordinary(123), ordinary(123)])
        with tempfile.TemporaryDirectory() as temp:
            _, terminal, _, _, _, warning = self.execute(socket, Path(temp))
        self.assertFalse(terminal)
        self.assertTrue(warning)
        self.assertEqual(len(socket.plays), 1)
        self.assertEqual(socket.replies[0], garbage)
        self.assertTrue(socket.closed)

    def test_return_without_debit_is_rejected_without_a_second_probe(self):
        socket = SyntheticWebSocket([INITIAL, ordinary(9975, 5),
                                     ordinary(9975, 0), ordinary(9975, 0)])
        with tempfile.TemporaryDirectory() as temp:
            _, terminal, _, _, _, warning = self.execute(socket, Path(temp))
        self.assertFalse(terminal)
        self.assertTrue(warning)
        self.assertEqual(len(socket.plays), 2)
        self.assertEqual(len(socket.replies), 1)
        self.assertTrue(socket.closed)

    def test_return_credit_mismatch_stops_before_any_further_play(self):
        # Expected 9975 - 20 + 4 = 9959, not 9958.
        socket = SyntheticWebSocket([INITIAL, ordinary(9975, 5),
                                     ordinary(9958, 4), ordinary(9938, 0)])
        with tempfile.TemporaryDirectory() as temp:
            _, terminal, _, _, _, warning = self.execute(socket, Path(temp))
        self.assertFalse(terminal)
        self.assertTrue(warning)
        self.assertEqual(len(socket.plays), 2)
        self.assertEqual(len(socket.replies), 1)
        self.assertTrue(socket.closed)

    def test_feature_in_return_probe_stays_unknown_without_continuing(self):
        garbage = {'type': 3, 'g': 702, 'st': 12, 'b8': 2, 'b9': 2, 'b': 123, 'w': 100}
        socket = SyntheticWebSocket([INITIAL, ordinary(9975, 5), bonus(9955),
                                     garbage, ordinary(123), ordinary(123)])
        with tempfile.TemporaryDirectory() as temp:
            _, terminal, _, _, _, warning = self.execute(socket, Path(temp))
        self.assertFalse(terminal)
        self.assertTrue(warning)
        self.assertEqual(len(socket.plays), 2)
        self.assertEqual(socket.replies[0], garbage)
        self.assertTrue(socket.closed)


if __name__ == '__main__':
    unittest.main()
