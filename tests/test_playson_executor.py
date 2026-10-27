import pathlib,sys,unittest,json
from xml.etree import ElementTree as ET
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.playson import validate_contract,verify_round,PlaysonProvider

class PlaysonExecutorTests(unittest.TestCase):
    def test_purchase_cost_uses_declared_multiplier_and_wallet(self):
        from tester_spin.providers import playson
        self.assertTrue(hasattr(playson,'verify_purchase_debit'),'Purchase debit verifier missing')
        reports=json.loads((ROOT/'tests/fixtures/playson-rest/purchase-wallets.json').read_text())['reports']
        count=0
        for report in reports:
            for event in report['events']:
                if event['buy'] is None:continue
                quote=playson.verify_purchase_debit(report['declarations'],event)
                self.assertEqual(quote['cost_minor'],event['wallet_before']-event['wallet_after'])
                self.assertFalse(quote['terminal'])
                broken=json.loads(json.dumps(event));broken['wallet_after']+=1
                with self.assertRaises(ValueError):playson.verify_purchase_debit(report['declarations'],broken)
                broken=json.loads(json.dumps(event));broken['buy']['type']='99'
                with self.assertRaises(ValueError):playson.verify_purchase_debit(report['declarations'],broken)
                count+=1
        self.assertEqual(count,6)
    def test_captured_base_round_reconciles(self):
        root=ET.parse(ROOT/'tests/fixtures/playson-rest/bet-response.xml').getroot()
        self.assertTrue(verify_round(root,before=1100000,total=100))
        for node,key,value in [('state','current_state','bonus'),('game','cash-bet','200'),('user_new','cash','1100000')]:
            root=ET.parse(ROOT/'tests/fixtures/playson-rest/bet-response.xml').getroot();root.find(node).set(key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):verify_round(root,before=1100000,total=100)
    def test_contract_requires_official_test_key_and_game(self):
        c=json.loads((ROOT/'tests/fixtures/playson-rest/synthetic-bootstrap-contract.json').read_text())
        self.assertTrue(validate_contract(c,'lucky-pots-x1000'))
        c['connect']['playerguid']='not-test'
        with self.assertRaises(ValueError):validate_contract(c,'lucky-pots-x1000')
    def test_registered_executor(self):
        from tester_spin.providers.registry import provider_class
        self.assertIs(provider_class('playson'),PlaysonProvider)
