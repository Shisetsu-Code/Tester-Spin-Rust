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

    def test_executor_rejects_unknown_feature_before_any_dispatch(self):
        from tester_spin.providers.amusnet_paths import execute_path
        sent=[]
        with self.assertRaisesRegex(ValueError,'FEATURE_DOMAIN_UNBOUND'):
            execute_path(self.f['init'],'UNKNOWN',20,gin=405,previous_round='-1',exchange=lambda *args:sent.append(args),save=lambda *args:None)
        self.assertEqual(sent,[])

    def test_executor_stops_on_uncertain_transport_without_retry(self):
        from tester_spin.providers.amusnet_paths import execute_path
        sent=[];saved=[]
        initial=copy.deepcopy(self.f['init']);initial['balance']=4999980
        def exchange(*args):
            sent.append(args)
            raise TimeoutError('synthetic lost response after dispatch')
        with self.assertRaises(TimeoutError):
            execute_path(initial,'BUY_FREESPINS',20,gin=405,previous_round='-1',exchange=exchange,save=lambda n,v:saved.append(n))
        self.assertEqual(len(sent),1)
        self.assertNotIn('settlement.json',saved)

    def test_executor_does_not_continue_after_bad_response_identity(self):
        from tester_spin.providers.amusnet_paths import execute_path
        initial=copy.deepcopy(self.f['init']);initial['balance']=4999980
        sent=[];pair=copy.deepcopy(self.paths[1][0]);pair['response']['messageId']='wrong'
        def exchange(*args):
            sent.append(args);return pair['request'],pair['response']
        with self.assertRaises(ValueError):
            execute_path(initial,'BUY_FREESPINS',20,gin=405,previous_round=pair['request']['gameNumber'],exchange=exchange,save=lambda *args:None)
        self.assertEqual(len(sent),1)

    def test_executor_bounds_pending_continuations_without_forging_settlement(self):
        from tester_spin.providers.amusnet_paths import execute_path
        initial=copy.deepcopy(self.f['init']);initial['balance']=4999980
        sent=[];saved=[];expected=copy.deepcopy(self.paths[1])
        def exchange(*args):
            pair=expected[len(sent)];sent.append(args);return pair['request'],pair['response']
        with self.assertRaisesRegex(ValueError,'PATH_STEP_LIMIT_UNCERTAIN'):
            execute_path(initial,'BUY_FREESPINS',20,gin=405,previous_round=expected[0]['request']['gameNumber'],exchange=exchange,save=lambda n,v:saved.append(n),max_steps=3)
        self.assertEqual(len(sent),3)
        self.assertNotIn('settlement.json',saved)

    def test_executor_collects_observed_gamble_state_without_inventing_choices(self):
        from tester_spin.providers.amusnet_paths import execute_path
        fixture=json.loads((ROOT/'tests/fixtures/amusnet-ws/candy-palace.json').read_text())
        expected=[(fixture['bet_sent'],fixture['bet_received']),(fixture['collect_sent'],fixture['collect_received'])]
        sent=[]
        def exchange(command,fields):
            request,response=expected[len(sent)]
            self.assertEqual(command,'bet')
            self.assertEqual(fields['bet'],request['bet'])
            sent.append(fields)
            return request,response
        pairs,receipt=execute_path(fixture['init_received'],'NONE',20,gin=405,previous_round='-1',exchange=exchange,save=lambda *args:None)
        self.assertEqual(len(pairs),2)
        self.assertEqual(receipt['state'],'CLOSED')
        self.assertEqual(receipt['balance_after'],4999988)
        self.assertEqual(receipt['gamble_choices'],[])
