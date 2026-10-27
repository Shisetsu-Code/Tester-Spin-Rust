import importlib.util,json,pathlib,shutil,sys,tempfile,unittest,xml.etree.ElementTree as ET
from decimal import Decimal
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.models import Game
FIXTURE=ROOT/'tests/fixtures/elk-capi-night';MODULE=ROOT/'evidence/campaign-20261026/elk-store.py'

class ElkCampaignImportTests(unittest.TestCase):
    def convert(self,source,destination):
        self.assertTrue(MODULE.exists(),'ELK campaign converter is not implemented')
        spec=importlib.util.spec_from_file_location('elk_store',MODULE);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        game=Game('elk','night-trax','Night Trax','https://www.elk-studios.com/games/night-trax/',symbol='10059')
        return module.convert_case(game,source,destination)

    def test_real_capture_covers_all_six_declared_modes_and_return(self):
        with tempfile.TemporaryDirectory() as temp:
            result=self.convert(FIXTURE,pathlib.Path(temp)/'result')
            # Closed CAPI modes do not by themselves certify every UI paid option.
            self.assertEqual(result.status,'PARCIAL',result.error)
            self.assertEqual(result.successful_spins,7)
            self.assertEqual(set(result.feature_domains['server_bmodes']['options']),{'DEF','X01','X02','X03','X04','X05'})
            self.assertFalse(result.structural_map['ui_inventory_verified'])
            self.assertIsNone(result.structural_map['paid_option_inventory']['count'])
            self.assertTrue(result.structural_map['elk_capi_validation']['all_declared_modes_closed'])

    def test_claimed_complete_run_with_dispatched_round_stays_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';shutil.copytree(FIXTURE,source)
            report=json.loads((source/'result.json').read_text());report['rounds'][2]['status']='dispatched';(source/'result.json').write_text(json.dumps(report))
            result=self.convert(source,pathlib.Path(temp)/'result')
            self.assertEqual(result.status,'PARCIAL')
            self.assertFalse(result.attempts[2].terminal)

    def test_inventory_is_checked_against_init_not_only_report(self):
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';shutil.copytree(FIXTURE,source)
            report=json.loads((source/'result.json').read_text());report['declaredModes']=[m for m in report['declaredModes'] if m['id']!='X05'];(source/'result.json').write_text(json.dumps(report))
            result=self.convert(source,pathlib.Path(temp)/'result')
            self.assertEqual(result.status,'PARCIAL')
            self.assertIn('X05',result.feature_domains['server_bmodes']['options'])

    def test_settlement_xml_disagreement_blocks_ok_even_if_summary_claims_success(self):
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';shutil.copytree(FIXTURE,source)
            file=source/'003-checkwin-response.redacted.xml';tree=ET.parse(file);balance=tree.find('player/balance');balance.text=str(Decimal(balance.text)+Decimal('.01'));tree.write(file,encoding='unicode')
            result=self.convert(source,pathlib.Path(temp)/'result')
            self.assertEqual(result.status,'PARCIAL')
            self.assertFalse(result.attempts[0].ok)

    def test_purchase_request_cost_must_match_the_declared_level(self):
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';shutil.copytree(FIXTURE,source)
            file=source/'002-purchase-request.redacted.xml';tree=ET.parse(file);tree.getroot().set('amount','99.00');tree.write(file,encoding='unicode')
            result=self.convert(source,pathlib.Path(temp)/'result')
            self.assertFalse(result.attempts[0].ok)

    def test_missing_settlement_is_not_synthesized_from_the_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';shutil.copytree(FIXTURE,source)
            (source/'003-checkwin-response.redacted.xml').unlink()
            result=self.convert(source,pathlib.Path(temp)/'result')
            self.assertFalse(result.attempts[0].terminal)

    def test_purchase_balance_must_confirm_the_actual_debit_before_win(self):
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';shutil.copytree(FIXTURE,source)
            file=source/'002-purchase-response.redacted.xml';tree=ET.parse(file);balance=tree.find('player/balance');balance.text=str(Decimal(balance.text)+Decimal('.01'));tree.write(file,encoding='unicode')
            result=self.convert(source,pathlib.Path(temp)/'result')
            self.assertFalse(result.attempts[0].ok)

if __name__=='__main__':unittest.main()
