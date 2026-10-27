import json,pathlib,sys,unittest,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class NetentExecutorTests(unittest.TestCase):
    def test_entry_uses_observed_direct_demo_flag(self):
        from tester_spin.providers import netent
        self.assertTrue(hasattr(netent,'validate_entry_fragment'))
        fragment={'demo':['direct'],'provider':['netent'],'table_id':['wildturkey000000'],'balance_id':['demo-fresh-virtual']}
        self.assertTrue(netent.validate_entry_fragment(fragment,'wildturkey000000'))
        for k,v in [('demo',['real']),('balance_id',['real-balance']),('provider',['other']),('table_id',['other'])]:
            changed={**fragment,k:v}
            with self.subTest(key=k),self.assertRaises(ValueError):netent.validate_entry_fragment(changed,'wildturkey000000')
    def test_captured_fun_round_and_mutations(self):
        from tester_spin.providers import netent
        f=json.loads((ROOT/'tests/fixtures/netent-servlet/base-round.json').read_text())
        initial=f['init']['response'];request=f['spin']['request'];response=f['spin']['response']
        self.assertEqual(netent.base_cost(initial,request),100)
        self.assertTrue(netent.verify_base_round(initial,request,response))
        for field,value in [('playforfun','false'),('gameover','false'),('nextaction','bonus'),('credit','100000')]:
            changed=copy.deepcopy(response);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):netent.verify_base_round(initial,request,changed)
        changed=copy.deepcopy(request);changed['bet.betlevel']='9999'
        with self.assertRaises(ValueError):netent.base_cost(initial,changed)

    def test_duplicate_form_keys_are_rejected(self):
        from tester_spin.providers import netent
        with self.assertRaises(ValueError):netent.decode_form('credit=100&credit=200')
