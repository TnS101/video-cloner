from __future__ import annotations
import importlib.util, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def mod(path,name):
 s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
capture=mod('resolve_workspace/modules/step_3B_6D_read_only_state_capture.py','capture')
class ReadOnlyTests(unittest.TestCase):
 def test_value_shapes_and_classifications(self):
  self.assertTrue(capture.equal('Center',{'1':.5,'2':.6},[.5,.6]));self.assertTrue(capture.equal('Size',.1,.1));self.assertFalse(capture.equal('Size',None,.1))
 def test_raw_key_mapping_keeps_ambiguity(self):
  class I:
   def GetKeyFrames(self): return {'x':{'value':1},2:{'value':2}}
   def GetConnectedOutput(self): return None
   def GetAttrs(self): return {'INPS_ID':'Center'}
  class T:
   Center=I()
   def FindInput(self,n): return self.Center
   def GetInput(self,n,f): return [.5,.5]
  data=capture.capture_property(T(),'Center',[{'local_frame':0,'timeline_frame':1}],1);self.assertTrue(any(x['mapping_ambiguous'] for x in data['keys']))
 def test_no_mutation_symbols_in_capture_module(self):
  text=(ROOT/'resolve_workspace/modules/step_3B_6D_read_only_state_capture.py').read_text();
  for forbidden in ('SetInput','SaveProject','DeleteModifier','AddModifier','ConnectTo','Disconnect') : self.assertNotIn(forbidden,text)
 def test_command_publisher_rejects_invalid_run_id(self):
  publisher=mod('scripts/davinci/prepare_step_3B_6D_read_only_state_capture_command.py','publisher');self.assertEqual(publisher.FAILED_RUN_ID,capture.FAILED_RUN_ID)
if __name__=='__main__': unittest.main()
