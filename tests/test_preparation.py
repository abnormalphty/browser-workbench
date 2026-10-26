"""Preparation continues from Docker startup without manual second steps."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from workbench.store import Store
from workbench.runtime import Runtime

class PreparationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.r=Runtime(Store(Path(self.tmp.name)))
 def tearDown(self):self.tmp.cleanup()
 def test_stopped_docker_is_opened_waited_for_then_image_is_built(self):
  statuses=[{'docker_installed':True,'docker_ready':False,'image_ready':False},{'docker_installed':True,'docker_ready':False,'image_ready':False},{'docker_installed':True,'docker_ready':True,'image_ready':False}]
  with patch.object(self.r,'status',side_effect=statuses),patch.object(self.r,'_open_desktop') as opened,patch.object(self.r,'_build_job') as built,patch('workbench.runtime.time.sleep'),patch.object(self.r.monitor,'engine_info'):
   self.r._prepare_job()
  opened.assert_called_once();built.assert_called_once()
 def test_ready_image_is_reused_without_rebuilding_or_opening_docker(self):
  with patch.object(self.r,'status',return_value={'docker_installed':True,'docker_ready':True,'image_ready':True}),patch.object(self.r,'_open_desktop') as opened,patch.object(self.r,'_build_job') as built:
   self.r._prepare_job()
  opened.assert_not_called();built.assert_not_called();self.assertEqual(self.r.build_state,'ready')
 def test_ready_runtime_starts_automatic_exit_detection(self):
  with patch.object(self.r,'status',return_value={'docker_installed':True,'docker_ready':True,'image_ready':True}),patch.object(self.r.geography,'start_batch') as start:
   self.r._prepare_job()
  start.assert_called_once_with(force=False)
  with patch.object(self.r,'status',return_value={'docker_installed':False,'docker_ready':False,'image_ready':False}),patch.object(self.r.geography,'start_batch') as start:
   self.r._prepare_job()
  start.assert_not_called()
 def test_missing_docker_explains_installation_without_trying_build(self):
  with patch.object(self.r,'status',return_value={'docker_installed':False,'docker_ready':False,'image_ready':False}),patch.object(self.r,'_open_desktop') as opened,patch.object(self.r,'_build_job') as built:
   self.r._prepare_job()
  opened.assert_not_called();built.assert_not_called();self.assertEqual(self.r.build_state,'error');self.assertIn('安装',self.r.build_error)
 def test_desktop_not_ready_times_out_with_actionable_message(self):
  with patch.object(self.r,'status',return_value={'docker_installed':True,'docker_ready':False,'image_ready':False}),patch.object(self.r,'_open_desktop'),patch.object(self.r,'_build_job') as built,patch('workbench.runtime.time.sleep'),patch.object(self.r.monitor,'engine_info'):
   self.r._prepare_job(attempts=2)
  built.assert_not_called();self.assertEqual(self.r.build_state,'error');self.assertIn('Docker',self.r.build_error)
