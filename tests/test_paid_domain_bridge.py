import json,pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.models import GameTestResult, SpinAttempt
from tester_spin.paid_options import ensure_paid_option_declaration
from tester_spin.providers.path_coverage import _paid_inventory_points

class PaidDomainBridgeTests(unittest.TestCase):
    def result(self,root,provider='hacksaw'):
        result=GameTestResult(provider,'random-game','Random','https://example.test',1,1,0,'OK',run_dir=str(root))
        result.feature_domains={'purchase':{'complete':True,'source':'authenticate.bonusGames/get_featureBuyItemType','options':['fs']},
                               'feature_spin':{'complete':True,'source':'authenticate.bonusGames/get_featureBuyItemType','options':[]}}
        result.discovered_modes=[{'id':'BUY_fs','kind':'PURCHASE','buyBonus':'fs','required_options':['fs'],'cost':100}]
        (root/'authenticate.response.raw.json').write_text('{"bonusGames":[{"bonusGameId":"fs"}]}')
        return result

    def test_maps_declared_wire_option_to_execution_mode_without_title_table(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result=self.result(pathlib.Path(temp))
            ensure_paid_option_declaration(result)
            inventory=result.structural_map['paid_option_inventory']
            self.assertTrue(inventory['complete'],inventory)
            self.assertEqual(inventory['count'],1)
            self.assertEqual(inventory['options'][0]['execution_ids'],['BUY_fs'])
            result.attempts=[SpinAttempt(1,True,mode_id='BUY_fs',terminal=True)]
            points=_paid_inventory_points(result)
            self.assertTrue(all(set(p['required'])<=set(p['covered']) for p in points),points)

    def test_missing_category_is_unknown_even_if_purchase_list_is_complete(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result=self.result(pathlib.Path(temp));del result.feature_domains['feature_spin']
            ensure_paid_option_declaration(result)
            self.assertFalse(result.structural_map['paid_option_inventory']['complete'])

    def test_unbound_advertised_option_is_not_dropped(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result=self.result(pathlib.Path(temp));result.feature_domains['purchase']['options'].append('unknown')
            ensure_paid_option_declaration(result)
            inventory=result.structural_map['paid_option_inventory']
            self.assertFalse(inventory['complete'])
            self.assertEqual(len(inventory['options']),2)

    def test_unknown_extra_mode_prevents_certifying_complete_inventory(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            result=self.result(pathlib.Path(temp));result.discovered_modes.append({'id':'mystery','kind':'UNKNOWN_FEATURE'})
            ensure_paid_option_declaration(result)
            self.assertFalse(result.structural_map['paid_option_inventory']['complete'])

    def test_bgaming_paid_spin_selectors_preserve_ante_and_purchase_roles(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            root=pathlib.Path(temp);result=self.result(root,'bgaming')
            result.feature_domains={'purchase':{'complete':True,'source':'init.options.feature_options.feature_multipliers','options':['freespin_buy']},
                                    'ante':{'complete':True,'source':'init.options.feature_options.feature_multipliers','options':['freespin_chance']}}
            result.discovered_modes=[{'id':'PURCHASE_FREESPIN_CHANCE','kind':'PURCHASE','purchased_feature':'freespin_chance','validated':True},
                                     {'id':'PURCHASE_FREESPIN_BUY','kind':'PURCHASE','purchased_feature':'freespin_buy','validated':True}]
            (root/'init-response.json').write_text('{"options":{"feature_options":{"feature_multipliers":{"freespin_chance":25,"freespin_buy":2000}}}}')
            ensure_paid_option_declaration(result)
            self.assertTrue(result.structural_map['paid_option_inventory']['complete'])
            self.assertEqual(result.structural_map['paid_option_inventory']['counts_by_category'],{'ante_bet':1,'bonus_purchase':1})
            from tester_spin.providers.path_coverage import _declared_feature_points
            self.assertTrue(all(set(p['required'])<=set(p['covered']) for p in _declared_feature_points(result)))

if __name__=='__main__':unittest.main()
