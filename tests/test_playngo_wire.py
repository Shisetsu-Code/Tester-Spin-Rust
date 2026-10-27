import pathlib,sys,json,base64,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))

class PlayngoWireTests(unittest.TestCase):
    def test_native_provider_registered_after_terminal_canary(self):
        from tester_spin.providers.registry import provider_class
        from tester_spin.providers.playngo import PlayNGoProvider
        from tester_spin.transport_policy import execution_profile
        self.assertIs(provider_class('playngo'),PlayNGoProvider)
        self.assertTrue(PlayNGoProvider.execution_supported)
        self.assertEqual(execution_profile('playngo')['gameplay'],'websocket')
    def test_initialization_uses_current_encoded_settings(self):
        from tester_spin.providers import playngo
        self.assertTrue(hasattr(playngo,'initialization_command'))
        c={'settings':'&settings=%3croot%3e%3c%2froot%3e'}
        self.assertEqual(playngo.initialization_command(c,910),'104 910 0 %22%3croot%3e%3c%2froot%3e%22')
    def test_http_bootstrap_preserves_observed_raw_line_format(self):
        from tester_spin.providers import playngo
        self.assertTrue(hasattr(playngo,'http_body'))
        self.assertEqual(playngo.http_body(2,'fresh-session','101 "" "" "" "" "" ""'),'d=2\r\nfresh-session\r\n101 "" "" "" "" "" ""\r\n')
    def test_captured_frames_including_multibyte_length(self):
        from tester_spin.providers import playngo
        frames=json.loads((ROOT/'tests/fixtures/playngo-gamehub/redacted-frames.json').read_text())
        for f in frames:
            raw=base64.b64decode(f['payload_b64']);decoded=playngo.decode_invocation(raw)
            self.assertEqual(decoded['target'],'ProcessPacket' if f['direction']=='sent' else 'Commands')
            self.assertTrue(decoded['payload'].startswith('d='))
            if f['direction']=='sent':self.assertEqual(playngo.encode_invocation(decoded['payload']),raw)
            with self.assertRaises(ValueError):playngo.decode_invocation(raw[:-1])

    def test_captured_settled_balance_requires_matching_game_reply(self):
        from tester_spin.providers import playngo
        text='d=1 1 10 10 0 6 8 0 3 4 1 2 2 2 3 2 1 3 7 0 0 2 1 3 1 4 0 0 7 10 4\r\n3 0 0 0 0 1\r\n6 0\r\n52 2499900 0 0\r\n'
        self.assertTrue(playngo.verify_base_reply(text,before=2500000,command='1 1 10 10 1',cost=100))
        for old,new in [('2499900','2500000'),('3 0 0 0 0 1','3 0 0 0 0 0'),('d=1 1 10 10','d=1 1 10 20')]:
            with self.subTest(old=old),self.assertRaises(ValueError):playngo.verify_base_reply(text.replace(old,new),before=2500000,command='1 1 10 10 1',cost=100)
