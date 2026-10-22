import importlib.util
import tempfile
import unittest
from pathlib import Path


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
        self.assertIsNone(module.infer_location('剩餘流量 55%'))

    def test_summer_and_winter_offsets_come_from_iana_rules(self):
        module=self.module()
        self.assertEqual(module.zone_offsets('America/New_York'),{'january':'UTC−05:00','july':'UTC−04:00'})
        self.assertEqual(module.zone_offsets('Asia/Tokyo'),{'january':'UTC+09:00','july':'UTC+09:00'})

        self.assertEqual(module.zone_offsets('Australia/Sydney'),{'january':'UTC+11:00','july':'UTC+10:00'})

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

if __name__=='__main__':unittest.main()
