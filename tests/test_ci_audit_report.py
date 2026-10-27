"""CI summaries must distinguish catalogue, execution evidence and final outcome."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AuditReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('ci_audit_report', ROOT/'scripts/ci_audit_report.py')
        self.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.audit)

    def tearDown(self):
        self.temp.cleanup()

    def catalog(self, provider='pragmatic', names=('Alpha', 'Beta', 'Gamma', 'Zeta')):
        from tester_spin.storage import Storage
        from tester_spin.models import Game
        store = Storage(self.root/'tester-spin.sqlite3')
        store.upsert_games([Game(provider, name.lower(), name, 'https://example.org/demo?token=private') for name in names])

    def result(self, provider='pragmatic', status='PARCIAL'):
        payload = dict(provider=provider, slug='alpha', game_name='Alpha', status=status,
                       successful_spins=1, failed_spins=1, requested_spins=2,
                       error='coverage missing token=private', feature_domains={'purchase': {'declaration_state': 'UNKNOWN'}},
                       attempts=[dict(mode_id='SPIN', mode_kind='SPIN', ok=True, terminal=True, error=''),
                                 dict(mode_id='BUY', mode_kind='BUY', ok=False, terminal=False, error='not covered')])
        with sqlite3.connect(self.root/'tester-spin.sqlite3') as con:
            con.execute("INSERT INTO test_results (provider,slug,game_name,game_url,status,requested_spins,successful_spins,failed_spins,started_at,finished_at,elapsed_ms,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (provider, 'alpha', 'Alpha', '', status, 2, 1, 1, '', '', 0, json.dumps(payload)))
        return payload

    def report(self, provider='pragmatic'):
        return self.audit.build_provider_report(provider, self.root, self.root/'output', limit=3, catalog_exit=0, run_exit=0, spins=2)

    def test_missing_results_are_never_success_or_attempted(self):
        self.catalog()
        report = self.report()
        self.assertEqual(report['selected'], 3)
        self.assertEqual(report['attempted'], 0)
        self.assertEqual(report['statuses'], {'NO_EJECUTADO': 4})
        self.assertTrue(all(row['status'] != 'OK' for row in report['games']))

    def test_unsupported_catalog_has_distinct_selected_state(self):
        self.catalog('netent')
        report = self.report('netent')
        self.assertFalse(report['execution_supported'])
        self.assertEqual(report['attempted'], 0)
        self.assertEqual(report['statuses'], {'SIN_EJECUTOR': 3, 'NO_EJECUTADO': 1})

    def test_partial_final_status_survives_a_closed_base_round(self):
        self.catalog()
        self.result()
        report = self.report()
        row = report['games'][0]
        self.assertEqual(row['status'], 'PARCIAL')
        self.assertEqual(row['closed_base_rounds'], 1)
        self.assertEqual(row['successful_spins'], 1)
        self.assertEqual(report['attempted'], 1)
        self.assertNotIn('private', json.dumps(report))

    def test_aggregate_counts_selected_separately_from_attempted(self):
        self.catalog()
        self.result()
        output = self.root/'providers'/'pragmatic'
        self.audit.write_reports(self.report(), output)
        combined = self.audit.aggregate_reports(self.root/'providers', self.root/'combined')
        self.assertEqual(combined['selected'], 3)
        self.assertEqual(combined['attempted'], 1)
        self.assertEqual(len(combined['games']), 4)
        self.assertTrue((self.root/'combined'/'audit.csv').is_file())

    def test_absent_catalog_does_not_create_database(self):
        report = self.report()
        self.assertEqual(report['state'], 'CATALOGO_FALLIDO')
        self.assertEqual(report['selected'], 0)
        self.assertFalse((self.root/'tester-spin.sqlite3').exists())

    def test_sanitized_evidence_cannot_upgrade_final_database_status(self):
        self.catalog()
        self.result()
        run_dir = self.root/'runs'/'one'
        run_dir.mkdir(parents=True)
        (run_dir/'result.json').write_text(json.dumps({'status': 'OK', 'sessionToken': 'private'}))
        (run_dir/'capture.har').write_text('private raw capture')
        with sqlite3.connect(self.root/'tester-spin.sqlite3') as con:
            payload = json.loads(con.execute('SELECT payload_json FROM test_results').fetchone()[0])
            payload['run_dir'] = str(run_dir)
            con.execute('UPDATE test_results SET payload_json=?', (json.dumps(payload),))
        original = (self.root/'tester-spin.sqlite3').read_bytes()
        report = self.report()
        row = report['games'][0]
        self.assertEqual(row['status'], 'PARCIAL')
        self.assertEqual(row['coverage_issues'][0]['code'], 'ARTIFACT_STATUS_DIFFERS')
        self.assertEqual(row['evidence'], ['evidence/0/result.json'])
        self.assertNotIn('private', (self.root/'output'/'evidence/0/result.json').read_text())
        self.assertEqual(original, (self.root/'tester-spin.sqlite3').read_bytes())
        self.assertFalse((self.root/'output'/'evidence/0/capture.har').exists())
        self.audit.write_reports(report, self.root/'output')
        combined = self.audit.aggregate_reports(self.root/'output', self.root/'combined')
        evidence = combined['games'][0]['evidence']
        self.assertEqual(evidence, ['evidence/pragmatic/0/result.json'])
        self.assertTrue((self.root/'combined'/evidence[0]).is_file())

    def test_empty_aggregate_fails(self):
        self.assertEqual(self.audit.main(['aggregate', '--input', str(self.root), '--output', str(self.root/'combined')]), 1)

    def test_result_without_attempts_is_recorded_but_not_gameplay(self):
        self.catalog()
        self.result()
        with sqlite3.connect(self.root/'tester-spin.sqlite3') as con:
            payload = json.loads(con.execute('SELECT payload_json FROM test_results').fetchone()[0])
            payload['attempts'] = []
            con.execute('UPDATE test_results SET payload_json=?', (json.dumps(payload),))
        report = self.report()
        self.assertEqual(report['result_recorded'], 1)
        self.assertEqual(report['attempted'], 0)

    def test_provider_base_conventions_count_closed_rounds_without_paid_modes(self):
        cases = [('elk', 'DEF', 'SPIN'), ('ka_gaming', 'SPIN', 'SLOTS'),
                 ('nolimit_city', 'RETURN_SPIN', 'SPIN')]
        for provider, identity, kind in cases:
            with self.subTest(provider=provider):
                self.catalog(provider)
                self.result(provider)
                with sqlite3.connect(self.root/'tester-spin.sqlite3') as con:
                    payload = json.loads(con.execute('SELECT payload_json FROM test_results WHERE provider=?', (provider,)).fetchone()[0])
                    payload['attempts'] = [dict(mode_id=identity, mode_kind=kind, ok=True, terminal=True),
                                           dict(mode_id='BUY', mode_kind='PURCHASE', ok=True, terminal=True),
                                           dict(mode_id=identity, mode_kind=kind, ok=True, terminal=True, warning='unverified')]
                    con.execute('UPDATE test_results SET payload_json=? WHERE provider=?', (json.dumps(payload), provider))
                report = self.report(provider)
                self.assertEqual(report['closed_base_rounds'], 1)
                self.assertEqual(report['games'][0]['status'], 'PARCIAL')

    def test_aggregate_repairs_old_counts_and_identifies_missing_providers(self):
        self.catalog('elk')
        self.result('elk')
        report = self.report('elk')
        row = report['games'][0]
        row['result']['attempts'][0]['mode_id'] = 'DEF'
        row['attempts'][0]['mode_id'] = 'DEF'
        row['closed_base_rounds'] = 0  # Previous reporter did not recognize DEF.
        report['closed_base_rounds'] = 0
        self.audit.write_reports(report, self.root/'providers'/'elk')
        combined = self.audit.aggregate_reports(self.root/'providers', self.root/'combined',
                                                expected_providers='elk,pragmatic')
        self.assertEqual(combined['closed_base_rounds'], 1)
        self.assertEqual(combined['providers'][0]['closed_base_rounds'], 1)
        self.assertEqual(combined['missing_providers'], ['pragmatic'])
        self.assertFalse(combined['complete'])
        self.assertEqual(len(combined['games']), 4)
        self.assertTrue(combined['errors'])
        self.assertIn('pragmatic', (self.root/'combined'/'audit.md').read_text())

    def test_catalog_diagnostic_excerpt_and_manifest_are_sanitized(self):
        output = self.root/'output'
        output.mkdir()
        (output/'selected-games.private.log').write_text('catalog parser failed token=private')
        (output/'selected-games.json').write_text(json.dumps({'provider': 'pragmatic', 'selected': 0,
                                                             'error': 'CATALOG_FAILURE', 'sessionToken': 'private'}))
        report = self.report()
        self.assertIn('catalog parser failed', report['log_excerpts']['selected-games.private.log'])
        self.assertEqual(report['catalog_manifest']['error'], 'CATALOG_FAILURE')
        self.assertNotIn('private', report['log_excerpts']['selected-games.private.log'])
        self.assertEqual(report['catalog_manifest']['sessionToken'], '[REDACTED]')

    def test_all_expected_reports_missing_still_produces_incomplete_audit(self):
        combined = self.audit.aggregate_reports(self.root/'missing', self.root/'combined',
                                                expected_providers='elk,pragmatic')
        self.assertEqual(combined['missing_providers'], ['elk', 'pragmatic'])
        self.assertFalse(combined['complete'])
        self.assertEqual(combined['games'], [])
        self.assertEqual(combined['selected'], 0)


if __name__ == '__main__':
    unittest.main()
