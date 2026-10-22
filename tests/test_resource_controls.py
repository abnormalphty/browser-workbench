import tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class ResourceControlsTests(unittest.TestCase):
 def test_existing_and_new_environment_have_preserving_resource_defaults(self):
  from workbench.store import Store
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp));e=s.create_environment('test',None)
   self.assertEqual(e.get('cpu_limit'),2)
   self.assertEqual(e.get('memory_limit_mb'),2048)
 def test_resource_validation_and_stats_use_cpu_cores_and_binary_memory(self):
  from workbench.resources import validate_limits,parse_stats
  self.assertEqual(validate_limits({'cpu_limit':1.5,'memory_limit_mb':1536}),{'cpu_limit':1.5,'memory_limit_mb':1536})
  for data in [{'cpu_limit':0,'memory_limit_mb':2048},{'cpu_limit':True,'memory_limit_mb':2048},{'cpu_limit':2,'memory_limit_mb':256}]:
   with self.assertRaises(ValueError):validate_limits(data)
  d=parse_stats({'CPUPerc':'150.50%','MemUsage':'512MiB / 2GiB','PIDs':'42'})
  self.assertEqual(d['cpu_cores'],1.505);self.assertEqual(d['memory_mb'],512);self.assertEqual(d['memory_limit_mb'],2048)
 def test_slots_count_unique_starting_running_and_paused_environments(self):
  from workbench.resources import occupied_ids
  self.assertEqual(occupied_ids({'a':{'State':{'Running':True,'Paused':True}},'b':{'State':{'Running':True}}},['b','c']),{'a','b','c'})
 def test_default_run_limit_is_preserved_and_can_be_changed(self):
  from workbench.store import Store
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp));self.assertEqual(s.resource_settings()['max_running'],2)
   s.save_resource_settings({'max_running':4});self.assertEqual(s.resource_settings()['max_running'],4)
   for value in [0,101,True,1.2]:
    with self.assertRaises(ValueError):s.save_resource_settings({'max_running':value})
