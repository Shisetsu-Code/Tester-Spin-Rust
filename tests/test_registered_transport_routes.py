import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'engine'))
from tester_spin.transport_policy import execution_profile

class RegisteredTransportTests(unittest.TestCase):
    def test_new_native_adapters_publish_http_route(self):
        for provider in ('pushgaming','relax','elk','playson'):
            with self.subTest(provider=provider):
                profile=execution_profile(provider)
                self.assertTrue(profile['contract_registered'])
                self.assertEqual(profile['gameplay'],'http')
                self.assertEqual(profile['browser_requirement'],'none')

    def test_catalogue_only_is_not_reported_as_executable(self):
        for provider in ('netent','pgsoft','blueprint','greentube','wazdan'):
            with self.subTest(provider=provider):
                self.assertFalse(execution_profile(provider)['contract_registered'])
