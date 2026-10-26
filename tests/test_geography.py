import importlib.util
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


class GeographyTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench.geography'))
        from workbench import geography
        return geography

    def test_country_marker_does_not_invent_a_us_city_or_timezone(self):
        geo=self.module().infer_location('🇺🇸 L+ 美國 AL-VT')
        self.assertEqual(geo['country_code'],'US')
        self.assertIsNone(geo['timezone'])
        self.assertEqual(geo['source'],'name')

    def test_known_city_and_unique_country_resolve_to_iana_zones(self):
        module=self.module()
        self.assertEqual(module.infer_location('纽约 美国 01')['timezone'],'America/New_York')
        self.assertEqual(module.infer_location('🇯🇵 日本 Ax')['timezone'],'Asia/Tokyo')
        self.assertEqual(module.infer_location('东京 02')['label'],'东京')
        self.assertEqual(module.infer_location('🇯🇵 大阪 03')['label'],'大阪')
        self.assertIsNone(module.infer_location('剩餘流量 55%'))

    def test_summer_and_winter_offsets_come_from_iana_rules(self):
        module=self.module()
        utc=timezone.utc
        winter,summer=datetime(2026,1,15,12,tzinfo=utc),datetime(2026,7,1,12,tzinfo=utc)
        new_york=module.zone_offsets('America/New_York',summer)
        self.assertEqual((new_york['january'],new_york['july'],new_york['standard'],new_york['daylight']),('UTC−05:00','UTC−04:00','UTC−05:00','UTC−04:00'))
        self.assertEqual((new_york['now'],new_york['dst_now']),('UTC−04:00',True))
        self.assertEqual((module.zone_offsets('America/New_York',winter)['now'],module.zone_offsets('America/New_York',winter)['dst_now']),('UTC−05:00',False))
        tokyo=module.zone_offsets('Asia/Tokyo',summer)
        self.assertEqual((tokyo['standard'],tokyo['daylight'],tokyo['dst_now']),('UTC+09:00',None,False))
        # Southern hemisphere: July is winter, January is summer time.
        sydney=module.zone_offsets('Australia/Sydney',summer)
        self.assertEqual((sydney['standard'],sydney['daylight'],sydney['now'],sydney['dst_now']),('UTC+10:00','UTC+11:00','UTC+10:00',False))
        self.assertTrue(module.zone_offsets('Australia/Sydney',winter)['dst_now'])
        # tzdata writes Dublin's winter as negative DST; the larger offset is still the summer one.
        dublin=module.zone_offsets('Europe/Dublin',winter)
        self.assertEqual((dublin['standard'],dublin['daylight'],dublin['dst_now']),('UTC+00:00','UTC+01:00',False))

    def test_exit_answers_become_locations_with_chinese_city_names(self):
        module=self.module()
        la=module.exit_location({'service':'ipwho.is','data':{'success':True,'country_code':'US','city':'Los Angeles','latitude':34.0522,'longitude':-118.2437,'timezone':{'id':'America/Los_Angeles'}}})
        self.assertEqual((la['label'],la['lat'],la['lon'],la['timezone'],la['source']),('洛杉矶',34.05,-118.24,'America/Los_Angeles','exit'))
        tokyo=module.exit_location({'service':'ipinfo.io','data':{'city':'Shinjuku','country':'JP','loc':'35.6938,139.7034','timezone':'Asia/Tokyo'}})
        self.assertEqual((tokyo['label'],tokyo['timezone']),('东京','Asia/Tokyo'))
        # No listed city nearby: the service's own name and point are kept.
        ashburn=module.exit_location({'service':'ipwho.is','data':{'success':True,'country_code':'US','city':'Ashburn','latitude':39.04,'longitude':-77.49,'timezone':{'id':'America/New_York'}}})
        self.assertEqual((ashburn['label'],ashburn['lat']),('Ashburn',39.04))
        for answer in [{},{'service':'ipwho.is','data':{'success':False}},{'service':'ipinfo.io','data':{'country':'US','loc':'1,2','timezone':'Not/AZone'}},{'service':'other','data':{}}]:
            with self.subTest(answer=answer),self.assertRaises((KeyError,ValueError)):
                module.exit_location(answer)

    def test_probe_script_is_valid_python(self):
        compile(self.module().PROBE_SCRIPT,'probe','exec')

    def test_remote_location_requires_valid_coordinates_and_iana_zone(self):
        module=self.module()
        location=module.validate_location({'country_code':'US','label':'New York','lat':40.7,'lon':-74,'timezone':'America/New_York','source':'exit'})
        self.assertEqual(location['timezone'],'America/New_York')
        with self.assertRaises(ValueError):
            module.validate_location({**location,'timezone':'UTC-5; arbitrary'})
        with self.assertRaises(ValueError):
            module.validate_location({**location,'lat':999})

    def test_existing_environment_timezone_policy_is_preserved(self):
        from workbench.store import Store
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            with sqlite3.connect(path/'workbench.sqlite3') as db:
                db.execute('CREATE TABLE environments (id TEXT PRIMARY KEY,name TEXT,node_id TEXT,fingerprint_seed TEXT,created_at REAL)')
                db.execute('INSERT INTO environments VALUES (?,?,?,?,?)',('a'*32,'old',None,'seed',1))
            store=Store(path)
            self.assertEqual(store.get_environment('a'*32).get('timezone_mode'),'legacy')
            self.assertEqual(store.create_environment('new',None).get('timezone_mode'),'node')

class AutomaticDetectionTests(unittest.TestCase):
    def setUp(self):
        from workbench.store import Store
        from workbench.runtime import Runtime
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name));self.runtime=Runtime(self.store)
        self.store.save_subscription('fixture',[{'name':name,'type':'http','server':name.split()[0].lower()+'.test','port':80} for name in
            ['New 名称推测 东京','Manual 手动','Fresh 新检测','Stale 旧检测','Failed 刚失败','Old 早失败','Info 剩余流量 10GB']])
        self.ids={n['name'].split()[0]:n['id'] for n in self.store.public_state()['nodes']}
        from workbench.geography import PLACES,validate_location
        now=time.time()
        self.store.set_setting('node_location:'+self.ids['Manual'],validate_location({**PLACES['london'],'source':'manual'}))
        self.store.set_setting('node_location:'+self.ids['Fresh'],validate_location({**PLACES['tokyo'],'source':'exit','checked_at':now-3600}))
        self.store.set_setting('node_location:'+self.ids['Stale'],validate_location({**PLACES['tokyo'],'source':'exit','checked_at':now-8*86400}))
        self.store.set_setting('location_failed:'+self.ids['Failed'],now-600)
        self.store.set_setting('location_failed:'+self.ids['Old'],now-13*3600)

    def tearDown(self):self.tmp.cleanup()

    def chosen(self,force):return sorted(n['name'].split()[0] for n in self.runtime.geography.candidates(force))

    def test_automatic_runs_skip_known_recent_and_info_entries(self):
        self.assertEqual(self.chosen(False),['New','Old','Stale'])
        # 重新检测 checks every route again, but never overrides a manual city or probes info entries.
        self.assertEqual(self.chosen(True),['Failed','Fresh','New','Old','Stale'])

    def test_failed_probe_is_remembered_and_docker_trouble_is_not(self):
        geo=self.runtime.geography
        node=self.ids['New']
        with patch.object(self.runtime,'_run',return_value=MagicMock(returncode=0,stdout='{}\n')):
            self.assertEqual(geo.locate(node,force=True)['source'],'name')  # keeps the name guess meanwhile
        self.assertGreater(self.store.get_setting('location_failed:'+node),time.time()-60)
        self.store.set_setting('location_failed:'+node,0)
        with patch.object(self.runtime,'_run',return_value=MagicMock(returncode=125,stdout='')):
            geo.locate(node,force=True)
        self.assertEqual(self.store.get_setting('location_failed:'+node),0)
        answer=json.dumps({'service':'ipwho.is','data':{'success':True,'country_code':'JP','city':'Tokyo','latitude':35.68,'longitude':139.69,'timezone':{'id':'Asia/Tokyo'}}})
        with patch.object(self.runtime,'_run',return_value=MagicMock(returncode=0,stdout=answer)):
            found=geo.locate(node,force=True)
        self.assertEqual((found['source'],found['label'],found['timezone']),('exit','东京','Asia/Tokyo'))

    def test_batch_waits_for_docker_and_runs_again_when_asked_meanwhile(self):
        geo=self.runtime.geography
        with patch.object(self.runtime,'status',return_value={'image_ready':False}),patch.object(geo,'locate') as locate:
            geo.start_batch(force=False);geo.batch.join(5)
        locate.assert_not_called()
        self.assertEqual(geo.progress['total'],0)
        release,calls=threading.Event(),[]
        def slow(node_id,force):
            calls.append(node_id);release.wait(5)
            return {'source':'exit'}
        with patch.object(self.runtime,'status',return_value={'image_ready':True}),patch.object(geo,'locate',side_effect=slow):
            geo.start_batch(force=False)
            geo.start_batch(force=True)   # arrives while the first batch runs
            self.assertTrue(geo.queued)
            release.set()
            for _ in range(100):
                if not geo.batch and len(calls)>=8:break
                time.sleep(.05)
        self.assertEqual(len(calls),3+5)  # the automatic three, then all five routes for 重新检测
        self.assertFalse(geo.progress['running'])


class EnvironmentTimezoneTests(unittest.TestCase):
    def setUp(self):
        from workbench.store import Store
        from workbench.runtime import Runtime
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name));self.runtime=Runtime(self.store)
        self.store.save_subscription('fixture',[{'name':'US fixture','type':'http','server':'example.test','port':80}])
        self.node=self.store.public_state()['nodes'][0]['id']

    def tearDown(self):self.tmp.cleanup()

    def environment(self,mode):
        env=self.store.create_environment('tz',self.node)
        with self.store.connect() as db:db.execute('UPDATE environments SET timezone_mode=? WHERE id=?',(mode,env['id']))
        return self.store.get_environment(env['id'])

    def launch_timezone(self,env,locate):
        def run(args,**options):
            if args[0]=='run':raise ValueError('stopped by the test')
            return MagicMock(returncode=0,stdout='')
        with patch.object(self.runtime,'_run',side_effect=run),patch.object(self.runtime.geography,'locate',side_effect=locate):
            self.runtime._start_job(env,{},False)
        launch=self.runtime.environment_paths(env['id'])[0]/'launch.json'
        return json.loads(launch.read_text())['timezone'] if launch.exists() else ('error',self.runtime.errors.get(env['id']))

    def test_every_environment_on_a_route_takes_the_route_time_zone(self):
        found=lambda node_id:{'timezone':'America/Los_Angeles'}
        self.assertEqual(self.launch_timezone(self.environment('node'),found),'America/Los_Angeles')
        self.assertEqual(self.launch_timezone(self.environment('legacy'),found),'America/Los_Angeles')

    def test_unknown_city_blocks_new_environments_but_not_old_ones(self):
        def unknown(node_id):raise ValueError('节点位置未能检测，请在“订阅与线路”中为该节点手动选择城市。')
        self.assertIsNone(self.launch_timezone(self.environment('legacy'),unknown))
        result=self.launch_timezone(self.environment('node'),unknown)
        self.assertEqual(result[0],'error');self.assertIn('手动选择城市',result[1])


if __name__=='__main__':unittest.main()
