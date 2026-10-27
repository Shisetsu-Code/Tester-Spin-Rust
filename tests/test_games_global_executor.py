import pathlib,sys,json,unittest,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class GamesGlobalExecutorTests(unittest.TestCase):
    def test_native_adapter_is_registered_after_live_canary(self):
        from tester_spin.providers.registry import provider_class
        from tester_spin.providers.games_global import GamesGlobalProvider
        from tester_spin.transport_policy import execution_profile
        self.assertIs(provider_class('games_global'),GamesGlobalProvider)
        self.assertTrue(GamesGlobalProvider.execution_supported)
        self.assertEqual(execution_profile('games_global')['gameplay'],'http')
    def test_declared_actions_preserve_paid_modes(self):
        from tester_spin.providers import games_global as gg
        fixture=json.loads((ROOT/'tests/fixtures/games-global/packets.json').read_text())
        initial=gg.packet(fixture[0]['response'],mid='101789',cid='50300',sid='22619')
        actions=gg.declared_actions(initial)
        self.assertEqual(len(actions),33)
        self.assertEqual(actions['PlayGuarantee']['sideBet'],'90')
        self.assertEqual(actions['PlayBonus1x4']['multiplier'],'85.00000000000000')
        self.assertEqual(gg.base_request(initial),{'verbex':'Spin','action':'Play','name':'BaseGame','denom':'2','level':'1','wager':'20'})
        self.assertTrue(hasattr(gg,'paid_options'))
        options=gg.paid_options(actions)
        self.assertEqual(len(options),32)
        self.assertEqual(sum(o['category']=='ante_bet' for o in options),2)
        self.assertEqual(sum(o['category']=='bonus_purchase' for o in options),30)

    def test_captured_terminal_and_pending_bonus_are_distinct(self):
        from tester_spin.providers import games_global as gg
        f=json.loads((ROOT/'tests/fixtures/games-global/packets.json').read_text())
        self.assertTrue(gg.verify_base_round(f[0]['response'],f[1]['request'],f[1]['response'],mid='101789',cid='50300',sid='22619'))
        with self.assertRaises(ValueError):gg.verify_base_round(f[1]['response'],f[2]['request'],f[2]['response'],mid='101789',cid='50300',sid='22619')
        bad=copy.deepcopy(f[1]['response']);bad['context']['balances']['totalInAccountCurrency']+=1
        with self.assertRaises(ValueError):gg.verify_base_round(f[0]['response'],f[1]['request'],bad,mid='101789',cid='50300',sid='22619')
        with self.assertRaises(ValueError):gg.packet(f[0]['response'],mid='wrong',cid='50300',sid='22619')
