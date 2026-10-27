import pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
import requests
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.rubyplay.adapter import RubyPlayProvider

class RubyCatalogTransportTests(unittest.TestCase):
    def test_catalog_ssl_failure_uses_verified_browser_and_closes_it(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            provider=RubyPlayProvider(pathlib.Path(temp));provider.http=Mock()
            provider.http.get.side_effect=requests.exceptions.SSLError('missing issuer')
            browser=Mock();browser.initial_document.return_value=('<html>catalog</html>','https://rubyplay.com/games/')
            with patch('tester_spin.providers.rubyplay.adapter.RubyPlayBrowserCatalogClient',return_value=browser):
                html,url=provider._initial_catalog_document(progress=lambda _:None)
            self.assertEqual(html,'<html>catalog</html>')
            self.assertEqual(url,provider.catalog_url)
            browser.close.assert_called_once()
            self.assertNotIn('verify',provider.http.get.call_args.kwargs)

    def test_unrelated_http_failure_is_not_silently_retried(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            provider=RubyPlayProvider(pathlib.Path(temp));provider.http=Mock()
            provider.http.get.side_effect=requests.HTTPError('503')
            with patch('tester_spin.providers.rubyplay.adapter.RubyPlayBrowserCatalogClient') as browser:
                with self.assertRaises(requests.HTTPError):provider._initial_catalog_document(progress=lambda _:None)
                browser.assert_not_called()

if __name__=='__main__':unittest.main()
