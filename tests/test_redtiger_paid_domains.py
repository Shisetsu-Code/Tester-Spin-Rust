import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class RedTigerPaidDomainsTests(unittest.TestCase):
    def test_explicit_empty_modifier_catalog_declares_zero(self):
        from tester_spin.providers.redtiger.modifiers import modifier_domains
        domains=modifier_domains({'gameModes':[],'mathModes':[]})
        self.assertTrue(domains['ante']['complete'])
        self.assertEqual(domains['special']['options'],[])

    def test_missing_modifier_catalog_does_not_mean_zero(self):
        from tester_spin.providers.redtiger.modifiers import modifier_domains
        self.assertFalse(modifier_domains({})['ante']['complete'])

    def test_orphan_math_modifier_blocks_complete_zero(self):
        from tester_spin.providers.redtiger.modifiers import modifier_domains
        domains=modifier_domains({'gameModes':[],'mathModes':[{'id':2,'type':'chanceIncrease','priceMultiplier':2,'name':'more'}]})
        self.assertFalse(domains['ante']['complete'])

if __name__=='__main__':unittest.main()
