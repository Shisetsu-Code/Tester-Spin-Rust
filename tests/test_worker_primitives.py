import base64
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from tester_spin.providers.elk_evidence import inspect_purchase_capture
from tester_spin.providers.playngo_evidence import inspect_frame

class WorkerPrimitiveTests(unittest.TestCase):
    def capture(self):
        path = ROOT / 'evidence/primitives-discovery-20261027/elk/ryze-2/xiter-bonus-hunt-1-redacted.json'
        return json.loads(path.read_text(encoding='utf-8'))['events'][0]

    def test_real_x01_acceptance_is_not_settlement_or_inventory(self):
        event = self.capture()
        result = inspect_purchase_capture(event, game_id='10260', quotes={'X01': {'4': '2.50'}}, currency='EUR')
        self.assertTrue(result['accepted'])
        self.assertFalse(result['terminal'])
        self.assertFalse(result['paid_inventory_complete'])
        self.assertEqual(result['mode'], 'X01')

    def test_wrong_quote_and_identity_rejected(self):
        for game, price in [('10261', '2.50'), ('10260', '1.00')]:
            with self.subTest(game=game, price=price), self.assertRaises(ValueError):
                inspect_purchase_capture(self.capture(), game_id=game, quotes={'X01': {'4': price}}, currency='EUR')

    def test_mismatched_round_or_currency_rejected(self):
        for old, new in [('<roundid>round-xiter-1</roundid>', '<roundid>other</roundid>'), ('<currency>EUR</currency>', '<currency>USD</currency>')]:
            event = copy.deepcopy(self.capture())
            event['response_body_xml'] = event['response_body_xml'].replace(old, new, 1)
            with self.subTest(old=old), self.assertRaises(ValueError):
                inspect_purchase_capture(event, game_id='10260', quotes={'X01': {'4': '2.50'}}, currency='EUR')

    def test_real_playngo_frames_remain_semantically_unknown(self):
        path = ROOT / 'evidence/primitives-discovery-20261027/playngo/divina-commedia/offline/fixtures/spin-1.raw.json'
        for frame in json.loads(path.read_text(encoding='utf-8'))['frames']:
            result = inspect_frame(base64.b64decode(frame['payload_b64']), opcode=2)
            self.assertIn(result['command'], {'Commands', 'ProcessPacket'})
            self.assertFalse(result['action_semantics_verified'])
            self.assertFalse(result['terminal'])

    def test_unknown_or_corrupt_frame_rejected(self):
        for data in [b'', b'\x00' * 30, b'\x0c' + b'\x00' * 5 + b'Unknown']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                inspect_frame(data, opcode=2)

    def test_server_rejection_or_public_cost_tamper_rejected(self):
        for old, new in [('<errorcode>0</errorcode>', '<errorcode>5</errorcode>'),
                         ('betamount="2.50000"', 'betamount="1.00000"'),
                         ('<balanceafterwin>4997.50</balanceafterwin>', '<balanceafterwin>5000.00</balanceafterwin>')]:
            event = copy.deepcopy(self.capture())
            event['response_body_xml'] = event['response_body_xml'].replace(old, new)
            with self.subTest(old=old), self.assertRaises(ValueError):
                inspect_purchase_capture(event, game_id='10260', quotes={'X01': {'4': '2.50'}}, currency='EUR')

if __name__ == '__main__':
    unittest.main()
