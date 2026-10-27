"""Synthetic D1 constructors for contracts observed in Actions 40550335443."""
import importlib
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from tester_spin.providers import one_spin4win_purchases as d1

BASE = '''var BasicSlotView=function(){BasicGameView.call(this);
this.useBuyFeature=!1;this.sideBetPercent=this.sideBet=0;
this.buyFeaturePlayIndex=this.sideBetPlayIndex=this.buyFeatureToPlayActionIndex=this.sideBetToPlayActionIndex=this.extraAnimationState=0;};
BasicSlotView.prototype.betDisplayAction=function(){1==this.sideBet?(this.sideBet=2,0<this.sideBetToPlayActionIndex&&(this.sideBetPlayIndex=this.sideBetToPlayActionIndex)):(this.sideBet=1,this.sideBetPlayIndex=0)};
BasicSlotView.prototype.getBetButtonValue=function(a){2==this.sideBet&&(a+=Math.round(a*this.sideBetPercent));return this.formatWinValue(a)};
SlotNetworkController.prototype.play=function(a,b,c){var d={key:this.gameController.sessionKey,type:"1",data:""+a+","+b+","+c};if(Game.game.useBuyFeature&&0<Game.game.sideBetPercent){var e=0;0<Game.game.buyFeaturePlayIndex?(e=Game.game.buyFeaturePlayIndex,Game.game.buyFeaturePlayIndex=0):0<Game.game.sideBet&&0<Game.game.sideBetPlayIndex&&(e=Game.game.sideBetPlayIndex);0<e&&(d={data:""+a+","+b+","+c+","+e.toString()})}else 0<Game.game.sideBet&&(d={data:""+a+","+b+","+c+","+(Game.game.sideBet-1).toString()},Game.game.useBuyFeature&&(Game.game.sideBet=0));d=JSON.stringify(d);this.sendData("A/u2"+d)};
SlotNetworkController.prototype.parseInitData=function(a){void 0!==a.bf&&"f"==a.bf&&(Game.game.useBuyFeature=!1)};
'''


class D1PaidDomainTests(unittest.TestCase):
    def contract(self, ctor='', *, complete=True, source=BASE):
        self.assertTrue(hasattr(d1, 'discover_paid_contract'), 'D1 has no tri-state client contract')
        return d1.discover_paid_contract([source + 'var TestView=function(){BasicSlotView.call(this);' + ctor + '};'],
                                        'Test', assets_complete=complete)

    def test_matching_inherited_disabled_flags_prove_empty_domains(self):
        contract = self.contract()
        for category in ('purchase', 'ante'):
            self.assertTrue(contract['feature_domains'][category]['complete'])
            self.assertEqual(contract['feature_domains'][category]['options'], [])
        self.assertTrue(contract['source_sha256'])

    def test_legacy_side_bet_has_selector_one_and_literal_half_price(self):
        contract = self.contract('this.sideBet=1;this.sideBetPercent=.5;')
        self.assertTrue(contract['feature_domains']['purchase']['complete'])
        self.assertTrue(contract['feature_domains']['ante']['complete'])
        mode = contract['antebet_modes'][0]
        self.assertEqual(mode['feature_selector'], 1)
        self.assertEqual(mode['cost_multiplier'], 1.5)
        self.assertEqual(contract['feature_domains']['ante']['options'], ['D1_ANTE_BET'])

    def test_unavailable_assets_or_constructor_do_not_prove_absence(self):
        for contract in (self.contract(complete=False),
                         self.contract(source=''), self.contract('this.useBuyFeature=runtimeFlag;')):
            self.assertFalse(contract['feature_domains']['purchase']['complete'])

    def test_conditional_or_overridden_paid_flags_remain_unknown(self):
        for ctor in ('if(enabled){this.useBuyFeature=true;}', 'this.useBuyFeature=false;if(enabled)this.useBuyFeature=true;',
                     'this.sideBet=1;this.sideBetPercent=runtimePrice;'):
            contract = self.contract(ctor)
            self.assertFalse(all(v['complete'] for v in contract['feature_domains'].values()))

    def test_unknown_serializer_does_not_execute_legacy_side_bet(self):
        contract = self.contract('this.sideBet=1;this.sideBetPercent=.5;', source=BASE.replace('(Game.game.sideBet-1)', '(Game.game.sideBet+1)'))
        self.assertFalse(contract['feature_domains']['ante']['complete'])
        self.assertFalse(any(m.get('executable') for m in contract['antebet_modes']))

    def test_other_parent_and_conditional_inherited_defaults_are_unknown(self):
        other = d1.discover_paid_contract([BASE + 'class OtherView{constructor(){this.useBuyFeature=true;}}'
                                          + 'class TestView extends OtherView{constructor(){super();}}'], 'Test')
        conditional = self.contract(source=BASE.replace('this.useBuyFeature=!1;',
                        'this.useBuyFeature=!1;if(enabled){this.useBuyFeature=true;}'))
        for contract in (other, conditional):
            self.assertFalse(contract['feature_domains']['purchase']['complete'])

    def test_parent_called_after_own_flags_does_not_certify_absence(self):
        source = BASE.replace('this.useBuyFeature=!1;', 'this.useBuyFeature=true;')
        source += 'var TestView=function(){this.useBuyFeature=false;BasicSlotView.call(this);};'
        self.assertFalse(d1.discover_paid_contract([source], 'Test')['feature_domains']['purchase']['complete'])

    def test_buy_disable_cannot_synthesize_absence_of_configured_ante(self):
        contract = self.contract()
        contract['antebet_modes'] = [{'id': 'configured-ante', 'kind': 'ANTE_BET', 'feature_selector': 3}]
        contract['feature_domains']['ante'].update(complete=True, options=['configured-ante'])
        bound = d1.bind_paid_contract_init(contract, {'type': 1, 'bf': 'f'})
        self.assertFalse(bound['feature_domains']['ante']['complete'])
        self.assertEqual(bound['feature_domains']['ante']['options'], ['configured-ante'])

    def test_buy_disable_init_preserves_independent_legacy_ante(self):
        contract = self.contract('this.sideBet=1;this.sideBetPercent=.5;')
        bound = d1.bind_paid_contract_init(contract, {'type': 1, 'bf': 'f'})
        self.assertEqual(bound['feature_domains']['ante']['options'], ['D1_ANTE_BET'])
        self.assertEqual(len(bound['antebet_modes']), 1)
        self.assertTrue(bound['init_bound'])

    def test_missing_init_never_binds_the_runtime_declaration(self):
        bound = d1.bind_paid_contract_init(self.contract(), {'type': 2})
        self.assertFalse(bound['init_bound'])
        self.assertFalse(any(d['complete'] for d in bound['feature_domains'].values()))

    def test_legacy_ante_quote_decodes_current_init_and_checks_debit(self):
        self.assertTrue(hasattr(d1, 'legacy_ante_cost'), 'Current D1 price quote missing')
        contract = self.contract('this.sideBet=1;this.sideBetPercent=.5;this.halfLines=!0;this.allWays=!1;this.forBetLinesDivider=1;')
        # D1 hex length-prefixed array: count 2, values 1 and 2.
        initial = {'type': 1, 'bs': '121112', 'b3': 0, 'l': 40, 'b1': 20, 'b2': 5000, 'b': 10000}
        self.assertEqual(d1.legacy_ante_cost(contract, initial), 30)
        d1.verify_ante_debit(initial, {'b': 9975, 'w': 5}, 30)
        with self.assertRaises(ValueError):
            d1.verify_ante_debit(initial, {'b': 9985, 'w': 5}, 30)
        for changed in ({'bs': '1211'}, {'b3': 3}, {'b1': 21}, {'l': True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                d1.legacy_ante_cost(contract, {**initial, **changed})
