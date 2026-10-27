import json,pathlib,sys,tempfile,threading,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.registry import create_provider
from tester_spin.models import Game

class CatalogRuntimeIdentityTests(unittest.TestCase):
    def test_catalog_without_runtime_id_does_not_erase_verified_metadata_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            provider=create_provider('elk',pathlib.Path(temp));game=Game('elk','night-trax','Night Trax','https://www.elk-studios.com/games/night-trax/')
            file=provider.game_dir(game)/'game.json'
            file.write_text(json.dumps({'provider':'elk','slug':game.slug,'symbol':'10059','launch_evidence':{'source':game.url,'sha256':'fixture'}}))
            provider.fetch_live_rows=lambda *_:[{'slug':game.slug,'name':game.name,'url':game.url,'symbol':''}]
            provider.crawl_catalog(stop_event=threading.Event(),progress=lambda _:None)
            self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['symbol'],'10059')

    def test_explicit_catalog_identity_replaces_the_previous_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evidence') as temp:
            provider=create_provider('elk',pathlib.Path(temp));game=Game('elk','night-trax','Night Trax','https://www.elk-studios.com/games/night-trax/')
            file=provider.game_dir(game)/'game.json'
            file.write_text(json.dumps({'provider':'elk','slug':game.slug,'symbol':'10059'}))
            provider.fetch_live_rows=lambda *_:[{'slug':game.slug,'name':game.name,'url':game.url,'symbol':'fresh-id'}]
            provider.crawl_catalog(stop_event=threading.Event(),progress=lambda _:None)
            self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['symbol'],'fresh-id')

if __name__=='__main__':unittest.main()
