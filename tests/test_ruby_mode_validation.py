"""Synthetic per-mode completion proofs; do not upgrade global coverage."""
import json
from pathlib import Path
import tempfile
import unittest

from tester_spin.models import GameTestResult, SpinAttempt
from tester_spin.providers.path_coverage import _declared_feature_points
from tester_spin.providers.rubyplay.execution import _mark_validated_modes


class RubyModeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.modes = [dict(id='PURCHASE_FREESPIN', kind='PURCHASE', executable=True),
                      dict(id='RUBYPLAY_PICK_INDEX_DOMAIN', kind='INDEXED_CHOICE',
                           coverage_required=True, required_options=['DOMAIN_UNRESOLVED'], covered_options=[])]
        self.attempts = []
        for number in range(2):
            directory = self.root/str(number)
            directory.mkdir()
            (directory/'return-to-base.json').write_text(json.dumps({'status': 'CONFIRMED', 'required': 2,
                                                                      'consecutive_base': 2}))
            self.attempts.append(SpinAttempt(number+1, True, mode_id='PURCHASE_FREESPIN',
                mode_kind='PURCHASE', terminal=True, artifact_dir=str(directory)))

    def mark(self):
        _mark_validated_modes(self.modes, self.attempts, self.root, {'PURCHASE_FREESPIN': 2})
        return self.modes[0].get('validated', False)

    def test_two_clean_terminal_samples_with_confirmed_returns_validate_only_root_mode(self):
        self.assertTrue(self.mark())
        self.assertEqual(self.modes[1]['required_options'], ['DOMAIN_UNRESOLVED'])
        self.assertEqual(self.modes[1]['covered_options'], [])
        self.assertNotIn('validated', self.modes[1])

    def test_missing_sample_never_sets_validated(self):
        self.attempts.pop()
        self.assertFalse(self.mark())

    def test_every_attempt_must_be_clean_and_terminal(self):
        for field, value in [('ok', False), ('terminal', False), ('warning', 'unsettled'),
                             ('error', 'LEDGER_MISMATCH')]:
            with self.subTest(field=field):
                old = getattr(self.attempts[1], field)
                setattr(self.attempts[1], field, value)
                self.assertFalse(self.mark())
                setattr(self.attempts[1], field, old)

    def test_missing_or_incomplete_return_proof_blocks_validated(self):
        proof = self.root/'1/return-to-base.json'
        for value in [{'status': 'INCOMPLETE', 'required': 2, 'consecutive_base': 2},
                      {'status': 'CONFIRMED', 'required': 2, 'consecutive_base': 1},
                      {'status': 'CONFIRMED', 'required': 1, 'consecutive_base': 1}, {}]:
            with self.subTest(proof=value):
                proof.write_text(json.dumps(value))
                self.assertFalse(self.mark())
        proof.unlink()
        self.assertFalse(self.mark())

    def test_duplicate_artifact_or_failed_extra_attempt_cannot_certify_mode(self):
        self.attempts[1].artifact_dir = self.attempts[0].artifact_dir
        self.assertFalse(self.mark())
        self.attempts[1].artifact_dir = str(self.root/'1')
        self.attempts.append(SpinAttempt(3, False, mode_id='PURCHASE_FREESPIN', mode_kind='PURCHASE',
                                         terminal=False, error='rejected'))
        self.assertFalse(self.mark())

    def test_declared_purchase_gate_receives_validation_without_resolving_ante(self):
        self.assertTrue(self.mark())
        result = GameTestResult('rubyplay', 'synthetic', 'Synthetic', '', 2, 2, 0, 'PARCIAL',
                                discovered_modes=self.modes, attempts=self.attempts,
                                feature_domains={'purchase': {'complete': True, 'source': 'explicit-init-menu',
                                                               'options': ['PURCHASE_FREESPIN']},
                                                 'ante': {'complete': False, 'source': 'unresolved-client', 'options': []}})
        points = {point['mode_id']: point for point in _declared_feature_points(result)}
        self.assertEqual(points['PURCHASE_DECLARATION']['covered'], ['PURCHASE_FREESPIN'])
        self.assertEqual(points['ANTE_DECLARATION']['required'], ['DOMAIN_UNRESOLVED'])
        self.assertEqual(points['ANTE_DECLARATION']['covered'], [])
        self.assertEqual(result.status, 'PARCIAL')


if __name__ == '__main__':
    unittest.main()
