"""Prize aliases must agree with the independent gameid sent in captured requests."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.yggdrasil.runtime import DemoRuntime, Unsupported, wager_state, collect_request, validate_transition

FIXTURES=[('yggdrasil-mace-replacement','captured-basic-mace.json'),
          ('yggdrasil-payline-base','captured.json'),
          ('yggdrasil-wild-lives','foxx-base-cascade.json')]


class Replay(DemoRuntime):
    def __init__(self,fixture):
        super().__init__(None,fixture['game_id'],5,threading.Event(),gate=None)
        self.config={'ordinary_constraints':fixture['constraints']}
        self.responses=deepcopy(fixture['responses'])
    def call(self,operation,body=None,query=None):return self.responses.pop(0)


class PrizeIdentityTests(unittest.TestCase):
    def fixtures(self):
        for folder,name in FIXTURES:
            fixture=json.loads((ROOT/'tests/fixtures'/folder/name).read_text())
            if 'samples' in fixture:fixture['responses']=fixture['samples'][0]['responses']
            yield folder,fixture
    def test_real_aliases_match_the_independent_captured_request_context(self):
        for family,fixture in self.fixtures():
            with self.subTest(family=family):
                self.assertEqual(fixture['game_id'],fixture['provenance']['game_id_source']['value'])
                runtime=Replay(fixture)
                with tempfile.TemporaryDirectory() as temp:result=runtime.round(fixture['template'],Path(temp))
                self.assertTrue(result['known'])
                self.assertTrue(result['base'])
    def test_mutating_only_prize_gameid_never_changes_the_trusted_context(self):
        for family,fixture in self.fixtures():
            with self.subTest(family=family):
                fixture['responses'][1]['data']['wager']['bets'][0]['prizes'][0]['gameId']=999999
                runtime=Replay(fixture)
                self.assertEqual(runtime.gameid,fixture['game_id'])
                with tempfile.TemporaryDirectory() as temp,self.assertRaises(Unsupported):
                    runtime.round(fixture['template'],Path(temp))
    def test_explicit_context_checks_every_present_alias_and_legacy_calls_remain_compatible(self):
        for family,fixture in self.fixtures():
            with self.subTest(family=family):
                before,after=map(wager_state,fixture['responses']);request=collect_request(before)
                after['bets'][0]['prizes'][0]['gameId']=999999
                self.assertIsNone(validate_transition(before,after,request,fixture['constraints']))
                with self.assertRaises(Unsupported):
                    validate_transition(before,after,request,fixture['constraints'],expected_game_id=fixture['game_id'])


if __name__=='__main__':unittest.main()
