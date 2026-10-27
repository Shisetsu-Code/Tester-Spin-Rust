"""Synthetic RubyPlay session declarations; no captured game data is invented."""
import unittest
import json
from pathlib import Path
import tempfile

from tester_spin.feature_domains import initialization_domains
from tester_spin.models import GameTestResult, SpinAttempt
from tester_spin.paid_options import ensure_paid_option_declaration
from tester_spin.providers.path_coverage import _paid_inventory_points


class RubyPaidDomainTests(unittest.TestCase):
    def setUp(self):
        self.init = dict(status='ok', topic='gameserver/init', data={'buy_feature_available': True,
                         'buy_feature_configs': [{'buyFeatureType': 'freespin_respin', 'priceMultiplier': 100}]})
        self.profile = dict(buy_feature_type='freespin_respin', buy_feature_multiplier=100,
                            wager=20, buy_feature_client_supported=True, bundle_sha256='a'*64,
                            evidence=['client.getBuyFeatureType->Action wrapper (method-local)'])
        self.modes = [dict(id='SPIN', kind='SPIN'), dict(id='PURCHASE_FREESPIN_RESPIN', kind='PURCHASE',
                      executable=True, wire_command='buy_feature', buy_feature_type='freespin_respin',
                      feature_multiplier=100)]

    def domains(self, init=None, profile=None, modes=None):
        return initialization_domains('rubyplay', init if init is not None else self.init,
                                      modes if modes is not None else self.modes,
                                      client_profile=profile if profile is not None else self.profile)

    def test_explicit_single_purchase_contract_binds_to_its_execution_id(self):
        domains = self.domains()
        self.assertTrue(domains['purchase']['complete'])
        self.assertEqual(domains['purchase']['options'], ['PURCHASE_FREESPIN_RESPIN'])
        self.assertEqual(domains['purchase']['client_source_sha256'], 'a'*64)
        self.assertFalse(domains['ante']['complete'])

    def test_missing_ante_does_not_become_zero_from_successful_base(self):
        domains = self.domains(init=dict(status='ok', topic='gameserver/init', data={'buy_feature_available': False}), modes=self.modes[:1])
        self.assertEqual(domains['purchase']['options'], [])
        self.assertTrue(domains['purchase']['complete'])
        self.assertFalse(domains['ante']['complete'])

    def test_missing_or_ambiguous_client_binding_remains_unknown(self):
        changes = [dict(bundle_sha256=''), dict(buy_feature_type=''), dict(buy_feature_multiplier=float('nan')),
                   dict(wager=True), dict(buy_feature_client_supported=None), dict(evidence=[])]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(self.domains(profile=dict(self.profile, **change))['purchase']['complete'])
        for modes in [self.modes[:1], self.modes + [dict(self.modes[1], id='ANOTHER_PURCHASE')]]:
            self.assertFalse(self.domains(modes=modes)['purchase']['complete'])

    def test_missing_session_flag_or_rejected_init_never_proves_absence(self):
        for init in [dict(status='ok', topic='gameserver/init', data={}),
                     dict(status='error', topic='gameserver/init', data={'buy_feature_available': False}),
                     dict(status='ok', topic='wrong', data={'buy_feature_available': False})]:
            with self.subTest(init=init):
                self.assertFalse(self.domains(init=init)['purchase']['complete'])

    def test_server_menu_cannot_be_replaced_by_one_client_type(self):
        menus = [None, [], [{'buyFeatureType': 'freespin_respin', 'priceMultiplier': 101}],
                 [{'buyFeatureType': 'freespin_respin', 'priceMultiplier': 100},
                  {'buyFeatureType': 'another_feature', 'priceMultiplier': 200}],
                 [{'buyFeatureType': 'freespin_respin', 'priceMultiplier': True}]]
        for menu in menus:
            with self.subTest(menu=menu):
                init = dict(self.init, data=dict(self.init['data'], buy_feature_configs=menu))
                self.assertFalse(self.domains(init=init)['purchase']['complete'])

    def test_effective_disabled_flag_requires_the_client_absence_proof(self):
        init = dict(status='ok', topic='gameserver/init', data={'buy_feature_available': False,
                    'buy_feature_available_server': True})
        self.assertFalse(self.domains(init=init)['purchase']['complete'])
        profile = dict(self.profile, buy_feature_type='', buy_feature_client_supported=False,
                       evidence=['client.buy-feature.contract=absent'])
        self.assertTrue(self.domains(init=init, profile=profile, modes=self.modes[:1])['purchase']['complete'])

    def test_paid_bridge_covers_executed_purchase_but_preserves_unknown_ante(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'bootstrap').mkdir()
            (root/'bootstrap/init-response.json').write_text(json.dumps(self.init))
            (root/'bootstrap/paid-client-profile.json').write_text(json.dumps(self.profile))
            result = GameTestResult('rubyplay', 'synthetic', 'Synthetic', '', 2, 2, 0, 'OK',
                                    run_dir=str(root), discovered_modes=self.modes,
                                    feature_domains=self.domains())
            result.attempts = [SpinAttempt(1, True, mode_id='PURCHASE_FREESPIN_RESPIN',
                                          mode_kind='PURCHASE', terminal=True)]
            ensure_paid_option_declaration(result)
            inventory = result.structural_map['paid_option_inventory']
            self.assertFalse(inventory['complete'])
            self.assertEqual(inventory['unresolved'], ['PAID_DOMAIN_INCOMPLETE:ante'])
            points = _paid_inventory_points(result)
            self.assertEqual(points[0]['covered'], [])
            self.assertEqual(points[1]['covered'], ['purchase:PURCHASE_FREESPIN_RESPIN'])


if __name__ == '__main__':
    unittest.main()
