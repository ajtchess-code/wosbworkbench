import unittest,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from emulator_research import create_research_manifest,validate_observation
class EmulatorEvidenceTests(unittest.TestCase):
 def test_records_never_claim_server_damage(self):
  with tempfile.TemporaryDirectory() as d:
   x=create_research_manifest(Path(d)/'Evidence.json')
   self.assertEqual(x['capabilities']['damage']['status'],'server_unverified')
   self.assertEqual(x['capabilities']['protocol']['status'],'unidentified')
 def test_observation_requires_version_no_credentials(self):
  self.assertEqual(validate_observation({'name':'observed hit','game_build':'abc','kind':'shot'}).status,'observed')
  with self.assertRaises(ValueError):validate_observation({'name':'shot','kind':'shot'})
  with self.assertRaises(ValueError):validate_observation({'name':'x','game_build':'g','kind':'x','input':{'session_key':'bad'}})
if __name__=='__main__':unittest.main()
