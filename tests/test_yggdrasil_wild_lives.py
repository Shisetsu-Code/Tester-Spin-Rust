"""Captured Foxx wild lifetimes and explicit synthetic negative mutations."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
sys.path.insert(0,str(ROOT/'tests'))
from test_yggdrasil_round_bindings import CapturedRuntime
from tester_spin.providers.yggdrasil import named_actions
from tester_spin.providers.yggdrasil.named_actions import ordinary_named_actions
from tester_spin.providers.yggdrasil.runtime import wager_state,continuation_request,Unsupported

FIXTURE=ROOT/'tests/fixtures/yggdrasil-wild-lives/foxx-base-cascade.json'


class WildLivesTests(unittest.TestCase):
    def fixture(self):return json.loads(FIXTURE.read_text())
    def data(self,fixture):return fixture['responses'][0]['data']['wager']['bets'][0]['eventdata']['response']['clientData']
    def recognized(self,fixture):
        return named_actions.ordinary_wild_life_round(fixture['responses'][0]['data']['wager']['bets'][0],fixture['constraints'])
    def replay(self,fixture):
        runtime=CapturedRuntime(fixture)
        with tempfile.TemporaryDirectory() as temp:result=runtime.round(fixture['template'],Path(temp))
        self.assertEqual(len(runtime.requests),2)
        self.assertEqual(runtime.requests[-1][1]['cmd'],'C')
        self.assertEqual(runtime.requests[-1][1]['amount'],'0')
        return result

    def test_captured_two_and_three_lives_decrement_only_after_their_winning_cascade(self):
        fixture=self.fixture();cd=self.data(fixture)
        self.assertTrue(self.recognized(fixture))
        before,after=map(wager_state,fixture['responses'])
        named_actions.validate_wild_life_collect(before,after,continuation_request(before,fixture['constraints']),fixture['constraints'])
        result=self.replay(fixture)
        self.assertTrue(result['known'])
        self.assertTrue(result['base'])
        self.assertTrue(result['terminal'])

    def test_life_metadata_without_the_bound_envelope_stays_unknown(self):
        self.assertFalse(ordinary_named_actions(self.data(self.fixture())))

    def test_unclosed_bonus_or_foreign_geometry_never_becomes_a_base_round(self):
        for mutation in ['bonus','pending','commands','outside_win','outside_create']:
            with self.subTest(mutation=mutation):
                fixture=self.fixture();root=fixture['responses'][0]['data']['wager']['bets'][0]
                ed=root['eventdata'];actions=ed['response']['clientData']['actions']
                if mutation=='bonus':ed['boostData']['boostDatas'][-1]['gameMode']='FREE_SPINS'
                elif mutation=='pending':ed['boostData']['boostDatas'][-1]['lastRespin']=False
                elif mutation=='commands':ed['playerState']['commands']=['FREE_SPIN']
                elif mutation=='outside_win':actions[17]['wins'][0]['positions'][0]={'column':19,'row':63}
                else:actions.append({'name':'operateSymbols','operation':'create','symbols':[{'position':{'column':19,'row':63},'subsymbol':False,'name':'WILD','lives':2}]})
                self.assertFalse(self.recognized(fixture))

    def test_root_cash_and_coin_aliases_must_agree_with_the_cascades(self):
        for path in [('wonamount',),('betdata','accWa'),('betdata','accC'),('eventdata','accWa'),('eventdata','accC'),('eventdata','response','cashWin'),('eventdata','response','coinWin')]:
            with self.subTest(path=path):
                fixture=self.fixture();target=fixture['responses'][0]['data']['wager']['bets'][0]
                for key in path[:-1]:target=target[key]
                target[path[-1]]='999'
                self.assertFalse(self.recognized(fixture))

    def test_collect_money_contradictions_are_rejected(self):
        for path in [('wonamount',),('betdata','accWa'),('betdata','accC'),('eventdata','exactWon')]:
            with self.subTest(path=path):
                fixture=self.fixture();target=fixture['responses'][1]['data']['wager']['bets'][0]
                for key in path[:-1]:target=target[key]
                target[path[-1]]='999'
                before,after=map(wager_state,fixture['responses'])
                request=continuation_request(before,fixture['constraints'])
                with self.assertRaises(ValueError):
                    named_actions.validate_wild_life_collect(before,after,request,fixture['constraints'])

    def test_collect_prizes_cannot_disagree_with_the_cash_receipt(self):
        for key,value in [('wonamount','999'),('netamount','999'),('woncurrency','USD'),('wonAspect','BONUS'),('type','UNBOUND')]:
            with self.subTest(key=key):
                fixture=self.fixture();fixture['responses'][1]['data']['wager']['bets'][0]['prizes'][0][key]=value
                before,after=map(wager_state,fixture['responses'])
                with self.assertRaises(ValueError):
                    named_actions.validate_wild_life_collect(before,after,continuation_request(before,fixture['constraints']),fixture['constraints'])

    def test_invalid_or_changed_life_budget_remains_unknown(self):
        for lives in [True,0,-1,4,'2',3]:
            with self.subTest(lives=lives):
                fixture=self.fixture();actions=self.data(fixture)['actions']
                next(s for a in actions for s in a.get('symbols',[])if'lives'in s)['lives']=lives
                self.assertFalse(self.recognized(fixture))

    def test_increased_or_skipped_remaining_life_identity_is_not_accepted(self):
        for name in ['WILD_3L','WILD','OTHER']:
            with self.subTest(name=name):
                fixture=self.fixture();actions=self.data(fixture)['actions']
                next(s for a in actions for s in a.get('symbols',[])if s.get('name')=='WILD_2L')['name']=name
                self.assertFalse(self.recognized(fixture))

    def test_decrement_requires_matching_creation_and_actual_winning_position(self):
        for mutation in ['missing_creation','not_consumed','wrong_position']:
            with self.subTest(mutation=mutation):
                fixture=self.fixture();actions=self.data(fixture)['actions']
                if mutation=='missing_creation':
                    actions[:]=[a for a in actions if not any(s.get('lives')==3 for s in a.get('symbols',[]))]
                elif mutation=='not_consumed':
                    win=actions[17]['wins'][0]
                    win['positions']=[p for p in win['positions']if p!={'column':2,'row':1}]
                else:
                    next(s for a in actions for s in a.get('symbols',[])if s.get('name')=='WILD_2L')['position']={'column':2,'row':5}
                self.assertFalse(self.recognized(fixture))

    def test_unexplained_shift_or_overwrite_cannot_reuse_old_life_identity(self):
        for action in [
            {'name':'shiftSymbols','positionShifts':[{'origin':{'column':2,'row':1},'target':{'column':2,'row':0}}]},
            {'name':'dropInReels','symbols':[{'position':{'column':2,'row':1},'subsymbol':False,'name':'OTHER'}]},
            {'name':'destroySymbols','positions':[{'column':2,'row':1}]},
            {'name':'fillSymbols','symbols':[{'position':{'column':2,'row':1},'type':'OTHER'}]},
            {'name':'bringNewSymbols','symbols':[{'position':{'column':2,'row':1},'type':'OTHER'}]},
            {'name':'operateSymbols','operation':'create','symbols':[{'position':{'column':2,'row':1},'subsymbol':False,'name':'OTHER'}]}]:
            with self.subTest(action=action):
                fixture=self.fixture();self.data(fixture)['actions'].insert(17,deepcopy(action))
                self.assertFalse(self.recognized(fixture))

    def test_synthetic_consistent_shift_preserves_the_life_identity(self):
        fixture=self.fixture();actions=self.data(fixture)['actions']
        old={'column':2,'row':1};new={'column':2,'row':5}
        actions[17]['wins'][0]['positions']=[new if p==old else p for p in actions[17]['wins'][0]['positions']]
        next(s for a in actions for s in a.get('symbols',[])if s.get('name')=='WILD_2L')['position']=new
        old_symbol=next(s['name'] for s in actions[1]['symbols'] if s['position']==new)
        actions[15:15]=[
            {'name':'operateSymbols','operation':'remove','symbols':[{'position':new,'subsymbol':False,'name':old_symbol}]},
            {'name':'shiftSymbols','positionShifts':[{'origin':old,'target':new}]}]
        self.assertTrue(self.recognized(fixture))


if __name__=='__main__':unittest.main()
