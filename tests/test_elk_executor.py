import sys,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
from tester_spin.providers.elk import validate_launch,request_xml,ElkProvider

class ElkExecutorTests(unittest.TestCase):
    def test_demo_launcher_identity_is_bound(self):
        url='https://gamelauncher-stage.contentmedia.eu/1.0/game/?mode=demo&operatorid=44&gameid=10256'
        self.assertEqual(validate_launch(url,'10256')['gameid'],['10256'])
        for modified in [url.replace('mode=demo','mode=real'),url.replace('operatorid=44','operatorid=1'),url.replace('contentmedia.eu','evil.example')]:
            with self.subTest(url=modified),self.assertRaises(ValueError):validate_launch(modified,'10256')
        with self.assertRaises(ValueError):validate_launch(url,'10000')
    def test_registry_enables_executor(self):
        from tester_spin.providers.registry import provider_class
        self.assertIs(provider_class('elk'),ElkProvider)
    def test_request_is_single_valid_xml_document(self):
        from xml.etree import ElementTree as ET
        body=request_xml({'opid':'44'})
        self.assertEqual(body.count(b'<?xml'),1)
        self.assertEqual(ET.fromstring(body).get('opid'),'44')
