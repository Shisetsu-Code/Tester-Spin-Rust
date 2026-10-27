import json,pathlib,sys,unittest,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class AmusnetExecutorTests(unittest.TestCase):
    def test_settlement_receipt_requires_verified_round(self):
        from tester_spin.providers import amusnet as a
        f=json.loads((ROOT/'tests/fixtures/amusnet-ws/candy-palace.json').read_text())
        receipt=a.settlement_receipt(f['init_received'],f['bet_sent'],f['bet_received'],f['collect_received'],gin=405)
        self.assertEqual(receipt['state'],'CLOSED')
        self.assertEqual(receipt['gin'],405)
        self.assertEqual(receipt['round_id'],f['bet_received']['gameNumber'])
        self.assertEqual(receipt['balance_after'],f['collect_received']['balance'])
        self.assertEqual(receipt['cost'],f['bet_sent']['bet']['bet'])
        self.assertFalse(receipt['paid_inventory_complete'])
        self.assertNotIn('sessionKey',json.dumps(receipt))
        with self.assertRaises(ValueError):
            a.settlement_receipt(f['init_received'],f['bet_sent'],f['bet_received'],None,gin=405)
        changed=copy.deepcopy(f['collect_received']);changed['balance']+=1
        with self.assertRaises(ValueError):
            a.settlement_receipt(f['init_received'],f['bet_sent'],f['bet_received'],changed,gin=405)

    def test_single_base_family_uses_observed_sdk_defaults_without_zero_claim(self):
        from tester_spin.providers import amusnet as a
        self.assertTrue(hasattr(a,'base_bet'))
        initial=json.loads((ROOT/'tests/fixtures/amusnet-ws/single-base-init.json').read_text())
        self.assertEqual(a.base_bet(initial),{'bet':10,'betMultiplier':1,'bonus':False,'featureId':0,'gameCommand':'bet'})
        initial['gameMetadata']['metadata']['engine']='UnknownEngine'
        with self.assertRaises(ValueError):a.base_bet(initial)
    def test_registered_native_fun_adapter(self):
        from tester_spin.providers.registry import provider_class
        from tester_spin.providers.amusnet import AmusnetProvider
        from tester_spin.transport_policy import execution_profile
        self.assertIs(provider_class('amusnet'),AmusnetProvider)
        self.assertTrue(AmusnetProvider.execution_supported)
        self.assertEqual(execution_profile('amusnet')['gameplay'],'websocket')
    def test_captured_win_requires_collect_and_reconciles(self):
        from tester_spin.providers import amusnet as a
        f=json.loads((ROOT/'tests/fixtures/amusnet-ws/candy-palace.json').read_text())
        self.assertTrue(a.verify_round(f['init_received'],f['bet_sent'],f['bet_received'],f['collect_received'],gin=405))
        with self.assertRaises(ValueError):a.verify_round(f['init_received'],f['bet_sent'],f['bet_received'],None,gin=405)
        for key,value in [('gameNumber','other'),('balance',5000000),('state','gamble')]:
            changed=copy.deepcopy(f['collect_received']);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):a.verify_round(f['init_received'],f['bet_sent'],f['bet_received'],changed,gin=405)

    def test_bonus_and_double_chance_are_preserved(self):
        from tester_spin.providers import amusnet as a
        f=json.loads((ROOT/'tests/fixtures/amusnet-ws/candy-palace.json').read_text());options=a.paid_options(f['init_received'])
        self.assertEqual({o['id'] for o in options},{'BUY_FREESPINS','DOUBLE_CHANCE'})
        self.assertEqual({o['category'] for o in options},{'bonus_purchase','ante_bet'})
