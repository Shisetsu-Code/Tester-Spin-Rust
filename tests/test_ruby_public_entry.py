import pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
import requests
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.rubyplay import runtime

class RubyPublicEntryTests(unittest.TestCase):
    def test_tls_failure_on_official_public_page_uses_existing_verified_browser_resolver(self):
        session=Mock();session.get.side_effect=requests.exceptions.SSLError('missing issuer')
        launcher='https://demo.example/launcher?mode=demo'
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp,patch('tester_spin.providers.rubyplay.browser_launcher.resolve_demo_launcher_browser',return_value=launcher) as browser:
            actual=runtime._resolve_public_launcher(session,'https://rubyplay.com/games/example/',timeout_s=5,artifact_dir=pathlib.Path(temp))
            self.assertEqual(actual,launcher);browser.assert_called_once()
            self.assertNotIn('verify',session.get.call_args.kwargs)
            self.assertNotIn(launcher,(pathlib.Path(temp)/'public-entry.json').read_text())

    def test_tls_failure_outside_public_authority_is_not_retried(self):
        session=Mock();session.get.side_effect=requests.exceptions.SSLError('bad cert')
        with patch('tester_spin.providers.rubyplay.browser_launcher.resolve_demo_launcher_browser') as browser:
            with self.assertRaises(requests.exceptions.SSLError):runtime._resolve_public_launcher(session,'https://other.example/games/example/',timeout_s=5)
            browser.assert_not_called()

if __name__=='__main__':unittest.main()
