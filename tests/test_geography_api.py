from unittest.mock import patch
import test_api
import unittest


class GeographyApiTests(unittest.TestCase):
    setUp=test_api.ApiTests.setUp
    tearDown=test_api.ApiTests.tearDown
    def test_manual_city_requires_token_and_persists_iana_zone(self):
        store=self.app.state.store
        store.save_subscription('fixture',[{'name':'US fixture','type':'http','server':'example.test','port':80}])
        node=store.public_state()['nodes'][0]
        route='/api/nodes/'+node['id']+'/location'
        self.assertEqual(self.client.post(route,json={'place_id':'new-york'}).status_code,403)
        result=self.client.post(route,json={'place_id':'new-york'},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        geo=store.public_state()['nodes'][0]['geo']
        self.assertEqual(geo['source'],'manual')
        self.assertEqual(geo['timezone'],'America/New_York')
        self.assertEqual(self.client.post(route,json={'place_id':'invalid'},headers=self.headers).status_code,400)

    def test_exit_probe_keeps_manual_choice_without_docker(self):
        from workbench.geography import PLACES,validate_location
        store=self.app.state.store
        store.save_subscription('fixture',[{'name':'US fixture','type':'http','server':'example.test','port':80}])
        node=store.public_state()['nodes'][0]
        store.set_setting('node_location:'+node['id'],validate_location({**PLACES['new-york'],'source':'manual'}))
        with patch.object(self.app.state.runtime,'_run',side_effect=AssertionError('Docker must not run')):
            self.assertEqual(self.app.state.runtime.geography.locate(node['id'],force=True)['source'],'manual')
