import json,pathlib,sys,unittest,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.relax import verify_round,validate_contract,RelaxProvider

class RelaxExecutorTests(unittest.TestCase):
    def fixture(self,name):return json.loads((ROOT/'tests/fixtures/relax-rest'/f'{name}.json').read_text(encoding='utf8'))
    def test_real_spin_and_gamefinished_reconcile(self):
        p=self.fixture('play')['response'];a=self.fixture('gamefinished')['response']
        self.assertTrue(verify_round(p,a,before=500000,bet=250))
        for field,value in [('ended',False),('subgameTriggered',True),('freeSpinAwardedCount',10)]:
            q=copy.deepcopy(p);q[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify_round(q,a,before=500000,bet=250)
    def test_wrong_ledger_or_stake_fails(self):
        p=self.fixture('play')['response'];a=self.fixture('gamefinished')['response'];a['b']+=1
        with self.assertRaises(ValueError):verify_round(p,a,before=500000,bet=250)
    def test_contract_rejects_real_login_or_mismatched_game(self):
        c=json.loads((ROOT/'data/providers/relax/diamondsdd/analysis/observed-rest-contract.json').read_text())
        self.assertTrue(validate_contract(c,'diamondsdd'))
        with self.assertRaises(ValueError):validate_contract(c,'moneytrain2')
        c['endpoint']=c['endpoint'].replace('stag-casino-client.api.relaxg.net','evil.example')
        with self.assertRaises(ValueError):validate_contract(c,'diamondsdd')
    def test_registry_uses_executor(self):
        from tester_spin.providers.registry import provider_class
        self.assertIs(provider_class('relax'),RelaxProvider)
