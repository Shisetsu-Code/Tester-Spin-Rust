import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.rubyplay.client_capability import _client_buy_feature_capability
from tester_spin.providers.rubyplay.runtime import RubyPlayClientProfile

class RubyCapabilityAbsenceTests(unittest.TestCase):
    def test_optional_wrapper_without_session_declaration_does_not_prove_absence(self):
        bundle='isBuyFeatureGame(){return this.getSession().isBuyFeatureGame?.()}'
        self.assertIsNone(_client_buy_feature_capability(bundle,RubyPlayClientProfile()))

    def test_explicit_session_false_remains_an_absence_declaration(self):
        bundle='isBuyFeatureGame(){return false}'
        self.assertIs(_client_buy_feature_capability(bundle,RubyPlayClientProfile()),False)

    def test_explicit_true_wins_over_base_false(self):
        bundle='isBuyFeatureGame(){return false} isBuyFeatureGame(){return true}'
        self.assertIs(_client_buy_feature_capability(bundle,RubyPlayClientProfile()),True)

if __name__=='__main__':unittest.main()
