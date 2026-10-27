import copy,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class AmusnetFeaturePathTests(unittest.TestCase):
    def setUp(self):
        self.f=json.loads((ROOT/'tests/fixtures/amusnet-ws/candy-palace-feature-paths.json').read_text())
        self.paths=[]
        for pair in self.f['pairs']:
            if pair['request']['bet'].get('bonus') is False:self.paths.append([])
            self.paths[-1].append(pair)

    def test_bonus_and_ante_paths_reconcile_and_require_full_close(self):
        from tester_spin.providers.amusnet_paths import verify_path
        for path in self.paths:
            initial=copy.deepcopy(self.f['init'])
            initial['balance']=path[0]['response']['balance']+path[0]['request']['bet']['bet']
            receipt=verify_path(initial,path,gin=405)
            self.assertEqual(receipt['state'],'CLOSED')
            self.assertEqual(receipt['balance_after'],path[-1]['response']['balance'])
        initial=copy.deepcopy(self.f['init']);initial['balance']=4999980
        bonus=self.paths[1]
        self.assertEqual(bonus[1]['response']['complex']['freespins'],0)
        with self.assertRaises(ValueError):verify_path(initial,bonus[:2],gin=405)

    def test_rejects_wrong_charge_continuation_identity_and_final_balance(self):
        from tester_spin.providers.amusnet_paths import verify_path
        initial=copy.deepcopy(self.f['init']);initial['balance']=4999980
        for field in ['identity','charge','bonus','ledger']:
            path=copy.deepcopy(self.paths[1])
            if field=='identity':path[1]['response']['gameNumber']='wrong'
            elif field=='charge':path[0]['request']['bet']['bet']+=1
            elif field=='bonus':path[1]['request']['bet']['bonus']=False
            else:path[-1]['response']['balance']+=1
            with self.subTest(field=field),self.assertRaises(ValueError):verify_path(initial,path,gin=405)

    def test_request_uses_effective_charge_and_observed_feature_domain(self):
        from tester_spin.providers.amusnet_paths import feature_bet
        self.assertEqual(feature_bet(self.f['init'],'BUY_FREESPINS',20)['bet'],1600)
        self.assertEqual(feature_bet(self.f['init'],'DOUBLE_CHANCE',20)['bet'],25)
        with self.assertRaises(ValueError):feature_bet(self.f['init'],'UNKNOWN',20)
        with self.assertRaises(ValueError):feature_bet(self.f['init'],'DOUBLE_CHANCE',21)

    def test_executor_runs_all_twelve_continuations_before_close(self):
        from tester_spin.providers.amusnet_paths import execute_path
        expected=copy.deepcopy(self.paths[1]);initial=copy.deepcopy(self.f['init']);initial['balance']=4999980
        sent=[];saved=[]
        def exchange(command,fields):
            pair=expected[len(sent)];request=pair['request']
            self.assertEqual(command,'bet')
            self.assertEqual(fields['bet'],request['bet'])
            self.assertEqual(fields['gameNumber'],request['gameNumber'])
            sent.append(fields)
            return request,pair['response']
        pairs,receipt=execute_path(initial,'BUY_FREESPINS',20,gin=405,previous_round=expected[0]['request']['gameNumber'],exchange=exchange,save=lambda n,v:saved.append(n))
        self.assertEqual(len(sent),13)
        self.assertEqual(receipt['balance_after'],4999368)
        self.assertIn('settlement.json',saved)
