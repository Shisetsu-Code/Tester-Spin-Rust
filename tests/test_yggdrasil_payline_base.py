"""Replay actual cash-normalized payline DTOs; no live transport."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.yggdrasil.runtime import DemoRuntime, Unsupported, ordinary_round
from tester_spin.return_to_base import verify_return_to_base


class Replay(DemoRuntime):
    def __init__(self,fixture):
        super().__init__(None,fixture.get('game_id','captured'),5,threading.Event(),gate=None)
        self.config={'ordinary_constraints':fixture['constraints']}
        self.responses=[deepcopy(response) for sample in fixture['samples'] for response in sample['responses']]
        self.requests=[]
    def call(self,operation,body=None,query=None):
        self.requests.append((operation,body))
        return self.responses.pop(0)


class PaylineBaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=json.loads((ROOT/'tests/fixtures/yggdrasil-payline-base/captured.json').read_text())
    def recognize(self,bet):
        module=ROOT/'engine/tester_spin/providers/yggdrasil/typed_payline_base.py'
        self.assertTrue(module.is_file(),'The captured payline DTO needs a semantic recognizer')
        return importlib.import_module('tester_spin.providers.yggdrasil.typed_payline_base').ordinary(bet,self.fixture['constraints'])
    def test_both_captured_payline_evaluations_are_recognized(self):
        for sample in self.fixture['samples']:
            self.assertTrue(self.recognize(sample['responses'][0]['data']['wager']['bets'][0]))
    def test_two_independent_rounds_still_required_and_captured_fields_preserved(self):
        runtime=Replay(self.fixture)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            proof=verify_return_to_base(root,lambda directory:runtime.round(self.fixture['template'],directory))
            self.assertEqual(proof['status'],'CONFIRMED')
            self.assertEqual(proof['consecutive_base'],2)
            self.assertEqual(len(proof['probes']),2)
            self.assertEqual(len(runtime.requests),4)
            self.assertNotEqual(proof['probes'][0]['round_ref'],proof['probes'][1]['round_ref'])
            saved=json.loads((root/'return-to-base/probe-001/step-001-response.json').read_text())
            expected=self.fixture['samples'][0]['responses'][0]['data']['wager']['bets'][0]['eventdata']['response']['clientData']
            self.assertEqual(saved['bets'][0]['clientData'],expected)
    def test_money_geometry_paylines_order_and_bonus_mutations_stay_unknown(self):
        mutations=('cash','normalized','ledger','currency','stake','coin_ledger','collect_choice','winning_cell','duplicate_cell',
                   'payline_outside','payline_disagrees','payline_missing_column','board_hole',
                   'board_counter','bonus_mode','unfinished','unknown_action','action_order','bonus_flag')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bet=deepcopy(self.fixture['samples'][0]['responses'][0]['data']['wager']['bets'][0])
                ed=bet['eventdata'];cd=ed['response']['clientData'];a=cd['actions'];win=a[3]
                if mutation=='cash':win['win']['amount']=999
                elif mutation=='normalized':win['win']['amountNormalizedToBet']=999
                elif mutation=='ledger':ed['accWa']='999'
                elif mutation=='currency':win['win']['currency']='USD'
                elif mutation=='stake':bet['betamount']='999'
                elif mutation=='coin_ledger':ed['accC']=1
                elif mutation=='collect_choice':ed['nextCmds']='C,Pick'
                elif mutation=='winning_cell':win['winningCells'][0]['y']=63
                elif mutation=='duplicate_cell':win['winningCells'][1]=deepcopy(win['winningCells'][0])
                elif mutation=='payline_outside':win['payline'][-1]['y']=63
                elif mutation=='payline_disagrees':win['payline'][0]['y']=(win['payline'][0]['y']+1)%3
                elif mutation=='payline_missing_column':win['payline'].pop()
                elif mutation=='board_hole':a[1]['board']['cells'].pop()
                elif mutation=='board_counter':a[1]['board']['counters']=[{'name':'spinsLeft','value':1}]
                elif mutation=='bonus_mode':a[0]['modeName']='BonusBlue'
                elif mutation=='unfinished':cd['isFinished']=False
                elif mutation=='unknown_action':a.insert(-1,{'$type':'ActionGame_Pick'})
                elif mutation=='action_order':a[-2],a[-3]=a[-3],a[-2]
                elif mutation=='bonus_flag':ed['freeSpins']=1
                self.assertFalse(self.recognize(bet))
                self.assertFalse(ordinary_round({'bets':[bet]},self.fixture['constraints']))
    def test_collect_wrong_identity_or_added_charge_still_rejected(self):
        for mutation in ('identity','charge','wonamount','exact_won','cash_ledger'):
            with self.subTest(mutation=mutation):
                fixture=deepcopy(self.fixture)
                collect=fixture['samples'][0]['responses'][1]['data']['wager']
                if mutation=='identity':collect['wagerid']='unrelated-round'
                elif mutation=='charge':collect['bets'][0]['betamount']='0.01'
                elif mutation=='wonamount':collect['bets'][0]['wonamount']='999'
                elif mutation=='exact_won':collect['bets'][0]['eventdata']['exactWon']='999'
                elif mutation=='cash_ledger':collect['bets'][0]['betdata']['accWa']='999'
                runtime=Replay(fixture)
                with tempfile.TemporaryDirectory() as temp, self.assertRaises(Unsupported):
                    runtime.round(fixture['template'],Path(temp))
    def test_collect_cash_prizes_must_reconcile_every_observed_money_alias(self):
        for mutation in ('wonamount','netamount','currency','type','aspect','empty','null','duplicate'):
            with self.subTest(mutation=mutation):
                fixture=deepcopy(self.fixture)
                bet=fixture['samples'][0]['responses'][1]['data']['wager']['bets'][0]
                prize=bet['prizes'][0]
                if mutation=='wonamount':prize['wonamount']='999.00'
                elif mutation=='netamount':prize['netamount']='999.00'
                elif mutation=='currency':prize['woncurrency']='USD'
                elif mutation=='type':prize['type']='BONUS'
                elif mutation=='aspect':prize['wonAspect']='FREE_SPINS'
                elif mutation=='empty':bet['prizes']=[]
                elif mutation=='null':bet['prizes']=None
                else:bet['prizes'].append(deepcopy(prize))
                runtime=Replay(fixture)
                with tempfile.TemporaryDirectory() as temp, self.assertRaises(Unsupported):
                    runtime.round(fixture['template'],Path(temp))
    def test_unknown_closed_round_stops_return_verification(self):
        fixture=deepcopy(self.fixture)
        fixture['samples'][0]['responses'][0]['data']['wager']['bets'][0]['eventdata']['response']['clientData']['actions'][0]['modeName']='UnboundMode'
        runtime=Replay(fixture)
        with tempfile.TemporaryDirectory() as temp:
            proof=verify_return_to_base(Path(temp),lambda directory:runtime.round(fixture['template'],directory))
        self.assertEqual(proof['status'],'REVIEW_REQUIRED')
        self.assertEqual(len(proof['probes']),1)
        self.assertTrue(proof['probes'][0]['terminal'])
        self.assertFalse(proof['probes'][0]['known'])
        self.assertFalse(proof['probes'][0]['base'])


if __name__=='__main__':unittest.main()
