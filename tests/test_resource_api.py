import unittest,tempfile,re,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from workbench.app import create_app

class ResourceApiTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app(Path(self.tmp.name));self.store=self.app.state.store;self.r=self.app.state.runtime
  self.c=TestClient(self.app,base_url='http://127.0.0.1:8766');self.h={'X-Workbench-Token':re.search(r'name="workbench-token" content="([^"]+)"',self.c.get('/').text)[1]};self.e=self.store.create_environment('Test',None)
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def test_new_resources_and_account_routes_require_authentication(self):
  for method,path in [('PATCH','resources/settings'),('PATCH',f'environments/{self.e["id"]}/resources'),('PATCH',f'environments/{self.e["id"]}/account'),('POST',f'environments/{self.e["id"]}/pause'),('POST',f'environments/{self.e["id"]}/account/check')]:
   self.assertEqual(self.c.request(method,'/api/'+path,json={}).status_code,403)
 def test_manual_account_keeps_plan_status_source_and_never_claims_page_verification(self):
  path='/api/environments/'+self.e['id']+'/account';data={'label':'QA@example.test','plan':'max','status':'active'}
  response=self.c.patch(path,json=data,headers=self.h);self.assertEqual(response.status_code,200,response.text)
  self.assertEqual(response.json()['source'],'manual');self.assertFalse(response.json()['verified'])
  self.assertEqual(self.c.patch(path,json={**data,'label':[]},headers=self.h).status_code,400)
  self.assertEqual(self.c.patch(path,json={**data,'plan':'injected'},headers=self.h).status_code,400)
 def test_global_limit_cannot_reduce_below_started_and_paused_slots(self):
  with patch.object(self.r,'occupied',return_value={'a','b'}):
   self.assertEqual(self.c.patch('/api/resources/settings',json={'max_running':1},headers=self.h).status_code,400)
   self.assertEqual(self.c.patch('/api/resources/settings',json={'max_running':3},headers=self.h).status_code,200)
  self.assertEqual(self.store.resource_settings()['max_running'],3)
 def test_stopped_resource_changes_persist_and_failed_live_update_does_not(self):
  identity=self.e['id'];path='/api/environments/'+identity+'/resources'
  with patch.object(self.r,'_inspect',return_value=None),patch.object(self.r.monitor,'engine_info',return_value={'ready':False}):
   self.assertEqual(self.c.patch(path,json={'cpu_limit':1,'memory_limit_mb':1024},headers=self.h).status_code,200)
  obj={'State':{'Running':True},'HostConfig':{'Memory':1024*1048576}}
  with patch.object(self.r,'_inspect',return_value=obj),patch.object(self.r,'_check_budget'),patch.object(self.r,'_validate_capacity'),patch.object(self.r,'_run',side_effect=ValueError('Docker rejected update')):
   self.assertEqual(self.c.patch(path,json={'cpu_limit':2,'memory_limit_mb':2048},headers=self.h).status_code,400)
  self.assertEqual(self.store.get_environment(identity)['memory_limit_mb'],1024)
 def test_paused_environment_does_not_contact_worker_and_stop_unpauses_first(self):
  identity=self.e['id'];obj={'State':{'Running':True,'Paused':True},'HostConfig':{'Memory':2048*1048576,'NanoCpus':2000000000}}
  with patch.object(self.r,'_inspect',return_value=obj),patch.object(self.r.monitor,'collect',return_value={identity:{'memory_mb':400}}),patch.object(self.r,'worker_address',side_effect=AssertionError('Paused worker must not be contacted')):
   self.assertEqual(self.r.state(identity)['status'],'paused')
  with patch.object(self.r,'_inspect',return_value=obj),patch.object(self.r.monitor,'collect',return_value={identity:{'memory_mb':0}}):
   self.assertIsNone(self.r.state(identity)['memory_mb'])
   self.assertTrue(self.r.state(identity)['memory_stale'])
  with patch.object(self.r,'_inspect',return_value=obj),patch.object(self.r,'_run') as run:
   self.r.stop(identity)
   self.assertEqual([call.args[0][0] for call in run.call_args_list],['unpause','stop'])
 def test_account_check_failure_keeps_previous_manual_record(self):
  from types import SimpleNamespace
  from workbench.accounts import check_account
  identity=self.e['id'];self.store.save_account_info(identity,{'label':'Known account','plan':'pro','status':'active'})
  with patch.object(self.r,'_inspect',return_value={'State':{'Running':True}}),patch.object(self.r,'_run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'verified':False,'plan':'unknown','status':'unknown'}))):
   result=check_account(self.r,identity)
  self.assertEqual(result['plan'],'pro');self.assertEqual(result['source'],'manual');self.assertFalse(result['verified']);self.assertTrue(result['last_attempt']);self.assertFalse(self.r.account_checking)
 def test_memory_budget_includes_paused_environment_and_prevents_unsafe_shrink(self):
  identity=self.e['id'];obj={'State':{'Running':True,'Paused':True},'HostConfig':{'Memory':2048*1048576}}
  with patch.object(self.r,'active_objects',return_value={identity:obj}),patch.object(self.r.monitor,'engine_info',return_value={'ready':True,'memory_mb':2500,'cpu_count':4}):
   with self.assertRaises(ValueError):self.r._check_budget(identity,2300)
  with patch.object(self.r,'_inspect',return_value=obj),patch.object(self.r,'_check_budget'),patch.object(self.r,'_validate_capacity'),patch.object(self.r.monitor,'collect',return_value={identity:{'memory_mb':900}}),patch.object(self.r,'_run',side_effect=AssertionError('Unsafe shrinking must not reach Docker')):
   with self.assertRaisesRegex(ValueError,'内存'):self.r.set_limits(identity,{'cpu_limit':1,'memory_limit_mb':1024})

 def test_pause_shrink_is_refused_even_after_monitor_cache_is_lost(self):
  identity=self.e['id'];self.r.monitor.metrics={}
  obj={'State':{'Running':True,'Paused':True},'HostConfig':{'Memory':2048*1048576}}
  with patch.object(self.r,'_inspect',return_value=obj),patch.object(self.r,'_check_budget'),patch.object(self.r,'_validate_capacity'),patch.object(self.r.monitor,'collect',return_value={identity:{'memory_mb':0}}),patch.object(self.r,'_run',side_effect=AssertionError('Paused memory must not shrink')):
   with self.assertRaisesRegex(ValueError,'先唤醒或停止'):self.r.set_limits(identity,{'cpu_limit':1,'memory_limit_mb':512})
