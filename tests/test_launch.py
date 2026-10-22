"""First launch and dependency-install recovery, without starting services."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import hashlib,subprocess
import launch

class LauncherTests(unittest.TestCase):
 def run_launcher(self,root,install_error=None):
  socket=MagicMock();socket.socket.return_value.__enter__.return_value.connect_ex.return_value=1
  with patch.object(launch,'ROOT',root),patch.object(launch,'healthy',side_effect=[False,True]),patch.object(launch,'socket',socket),patch.object(launch.venv,'EnvBuilder') as builder,patch.object(launch.subprocess,'run',side_effect=install_error) as install,patch.object(launch.subprocess,'Popen') as start,patch.object(launch.webbrowser,'open'):
   def create(path):
    (path/'bin').mkdir(parents=True);(path/'bin/python').touch()
   builder.return_value.create.side_effect=create
   launch.main()
   return builder,install,start
 def test_fresh_launch_installs_pinned_dependencies_into_project_venv(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'requirements.txt').write_text('httpx==0.28.1\n')
   builder,install,start=self.run_launcher(root)
   builder.return_value.create.assert_called_once_with(root/'.venv')
   self.assertEqual(install.call_args.args[0],[str(root/'.venv/bin/python'),'-m','pip','install','-r',str(root/'requirements.txt')])
   self.assertTrue((root/'.venv/.workbench-requirements.sha256').exists())
   self.assertEqual(start.call_args.args[0][0],str(root/'.venv/bin/python'))
 def test_existing_venv_retries_install_if_marker_missing(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'requirements.txt').write_text('requirements\n');(root/'.venv/bin').mkdir(parents=True);(root/'.venv/bin/python').touch()
   builder,install,_=self.run_launcher(root);builder.return_value.create.assert_not_called();install.assert_called_once()
 def test_failed_install_never_marks_requirements_as_ready(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'requirements.txt').write_text('requirements\n')
   with self.assertRaises(subprocess.CalledProcessError):self.run_launcher(root,subprocess.CalledProcessError(1,'pip'))
   self.assertFalse((root/'.venv/.workbench-requirements.sha256').exists())
