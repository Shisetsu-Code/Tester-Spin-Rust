import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class RubyRestCatalogTests(unittest.TestCase):
    def row(self):return {'id':295,'slug':'go-high-harvest','link':'https://rubyplay.com/games/go-high-harvest/','title':{'rendered':'Go High&reg; Harvest'}}
    def parse(self,rows):
        from tester_spin.providers.rubyplay.rest_catalog import parse_page
        return parse_page({'status':200,'total':'1','pages':'1','data':rows})
    def test_published_game_identity_and_title_are_preserved(self):
        games,total,pages=self.parse([self.row()])
        self.assertEqual((total,pages),(1,1));self.assertEqual(games[0].name,'Go High® Harvest')
        self.assertEqual(games[0].slug,'go-high-harvest')
    def test_off_authority_link_is_rejected(self):
        row=self.row();row['link']='https://example.test/games/go-high-harvest/'
        with self.assertRaises(ValueError):self.parse([row])
    def test_duplicate_identity_is_rejected(self):
        with self.assertRaises(ValueError):self.parse([self.row(),self.row()])

if __name__=='__main__':unittest.main()
