import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.catalogs.fetch import parse_html
from tester_spin.providers.catalogs.adapter import validate_rows

class PlaysonCatalogTests(unittest.TestCase):
    def test_play_action_is_not_a_second_game_with_a_different_title(self):
        source='<a href="https://playson.com/game/lucky-pots-x1000#autoplay">Play Lucky Pots x1000</a><a href="https://playson.com/game/lucky-pots-x1000">Lucky Pots x1000</a>'
        rows=validate_rows('playson',parse_html('playson',source))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['name'],'Lucky Pots x1000')
        self.assertNotIn('#',rows[0]['url'])

    def test_a_real_title_starting_with_play_is_preserved(self):
        rows=validate_rows('playson',parse_html('playson','<a href="https://playson.com/game/play-the-stars">Play the Stars</a>'))
        self.assertEqual(rows[0]['name'],'Play the Stars')

    def test_real_canonical_identity_conflicts_are_still_rejected(self):
        source='<a href="https://playson.com/game/same">First</a><a href="https://playson.com/game/same">Different</a>'
        with self.assertRaises(ValueError):validate_rows('playson',parse_html('playson',source))

if __name__=='__main__':unittest.main()
