import base64,json,pathlib,sys,unittest,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.pushgaming import parse_launcher,verify_round,action_identity,PushGamingProvider

class PushExecutorTests(unittest.TestCase):
    def pair(self):
        fixture=json.loads((ROOT/'tests/fixtures/push-hive/synthetic-numeric-data-round.json').read_text())
        self.assertEqual(fixture['_fixture']['kind'],'synthetic-unit-contract')
        return fixture['purchase'],fixture['settlement']
    def test_synthetic_base_round_reconciles_only_after_ack(self):
        a,b=self.pair();self.assertTrue(verify_round(a,b,before=100000,bet=50))
        b['actionComplete']=False
        with self.assertRaises(ValueError):verify_round(a,b,before=100000,bet=50)
    def test_other_round_or_wallet_tamper_rejected(self):
        for field,value in [('actionId','other'),('walletData',{'walletBalance':100000})]:
            a,b=self.pair();b[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify_round(a,b,before=100000,bet=50)
    def test_launcher_is_official_demo_and_no_external_authority(self):
        html=(ROOT/'tests/fixtures/push-hive/synthetic-public-launcher.html').read_text(encoding='utf8')
        launch=parse_launcher(html);self.assertEqual(launch['mode'],'DEMO')
        bad='var gameUrl = '+repr(base64.b64encode(b'https://evil.example/launch?mode=DEMO').decode())+';'
        with self.assertRaises(ValueError):parse_launcher(bad)
    def test_registry_uses_real_executor(self):
        from tester_spin.providers.registry import provider_class
        self.assertIs(provider_class('pushgaming'),PushGamingProvider)
    def test_ack_uses_actual_numeric_action_identity(self):
        a,_=self.pair();self.assertEqual(action_identity(a),str(a['actionId']))
        for value in [True,None,'../other']:
            with self.subTest(value=value),self.assertRaises(ValueError):action_identity({'actionId':value})
    def test_captured_step_dialect_closes_and_rejects_feature_transition(self):
        for slug in ['big-bamboo','jammin-jars','jammin-jars-cascade']:
            d=json.loads((ROOT/'tests/fixtures/push-hive'/f'{slug}.json').read_text(encoding='utf8'))
            with self.subTest(slug=slug):
                self.assertTrue(verify_round(d['purchase'],d['settlement'],before=d['before'],bet=d['bet']))
                d['settlement']['steps'][0]['gameMode']='free-spins'
                with self.assertRaises(ValueError):verify_round(d['purchase'],d['settlement'],before=d['before'],bet=d['bet'])

if __name__=='__main__':unittest.main()
