import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
import io
import shapefile
from pyproj import Transformer
from hdmap_pipeline import Pipeline, write_shp_zip


def feat(geometry, **properties):
    return {'type':'Feature','properties':properties,'geometry':geometry}


def line(x=114.85):
    return {'type':'LineString','coordinates':[[x,40.8],[x+0.0001,40.8001]]}


def polygon(x=114.85):
    return {'type':'Polygon','coordinates':[[[x,40.8],[x+0.00004,40.8],[x+0.00004,40.80005],[x,40.80005],[x,40.8]]]}


class PipelineTest(unittest.TestCase):
    def setUp(self):
        root=Path(os.environ['HDMAP_TEST_WORKSPACE']);root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def source(self,name,features,crs=None):
        d={'type':'FeatureCollection','features':features}
        if crs:d['crs']={'type':'name','properties':{'name':crs}}
        p=self.root/name;p.write_text(json.dumps(d,ensure_ascii=False));return p

    def execute(self,entries,**kw):
        cfg={'profile':'legacy2023','coordinate_basis':'wgs84','output_prefix':'test','deduplicate_exact':True,'inputs':entries,**kw}
        m=self.root/'manifest.json';m.write_text(json.dumps(cfg));return Pipeline(m,self.root/'output').run()

    def test_merge_conservation_and_unicode_shp_roundtrip(self):
        f=feat(line(),id=0,中文字段='张家口',precise=0.1234567890123456)
        a=self.source('a.geojson',[f,feat(None,id=1)])
        b=self.source('b.geojson',[f,feat(line(114.86),id=2,中文字段='桥东')])
        result=self.execute([{'path':str(p),'role':'hdmap','layer':'2_cross_border_ln'} for p in (a,b)])
        self.assertEqual(result['totals'],{'input':4,'output':2,'deduplicated':1,'quarantined':1})
        self.assertFalse(any(x['code']=='SHP_EXPORT_FAILED' for x in result['issues']))
        gj=json.loads((self.root/'output/01_高精地图/GeoJSON/test_2_cross_border_ln.geojson').read_text())
        self.assertEqual(gj['features'][0]['properties']['precise'],0.1234567890123456)
        ledger=json.loads((self.root/'output/审核/provenance.json').read_text())
        self.assertIn('kept_uid',next(x for x in ledger if x['disposition']=='deduplicated'))

    def test_detector_composite_keys_aliases_and_direction(self):
        a=self.source('a.geojson',[feat(polygon(),LaneId=101,LaneEventD=1),feat(polygon(114.851),LaneId=111,LaneEventD=2)])
        b=self.source('b.geojson',[feat(polygon(),LaneId='101',LaneEventD='1')])
        r=self.execute([{'path':str(p),'role':'detector','layer':'detector_merge','intersection_id':iid,'field_map':{'LaneEventD':'LaneEventDetectorCategoryId'}} for p,iid in [(a,'A'),(b,'B')]])
        self.assertEqual(r['totals']['output'],2)
        self.assertEqual(r['totals']['quarantined'],1)
        self.assertEqual(r['totals']['deduplicated'],0)
        self.assertTrue(any(x['code']=='DETECTOR_DIRECTION_CONFLICT' for x in r['issues']))
        self.assertFalse(any(x['code']=='DETECTOR_KEY_CONFLICT' for x in r['issues']))

    def test_projected_geojson_transform(self):
        t=Transformer.from_crs(4326,32650,always_xy=True)
        g=line();g['coordinates']=[list(t.transform(*p)) for p in g['coordinates']]
        p=self.source('projected.geojson',[feat(g,id=1)],'EPSG:32650')
        r=self.execute([{'path':str(p),'role':'hdmap','layer':'2_cross_border_ln'}])
        self.assertEqual(r['totals']['output'],1)
        self.assertTrue(any(x['code']=='CRS_TRANSFORMED' for x in r['issues']))
        d=json.loads((self.root/'output/01_高精地图/GeoJSON/test_2_cross_border_ln.geojson').read_text())
        self.assertAlmostEqual(d['features'][0]['geometry']['coordinates'][0][0],114.85,places=10)

    def test_spec_change_is_blocking(self):
        p=self.source('line.geojson',[feat(line(),id=1)])
        r=self.execute([{'path':str(p),'role':'hdmap','layer':'6_laneline_W_ln'}],profile='spec20241118')
        self.assertEqual(r['status'],'BLOCKED')
        self.assertTrue(any(x['code']=='SPEC_REQUIRES_POLYGON' for x in r['issues']))

    def test_invalid_polygon_is_quarantined_not_repaired(self):
        g={'type':'Polygon','coordinates':[[[114,40],[114.001,40.001],[114,40.001],[114.001,40],[114,40]]]}
        p=self.source('bad.geojson',[feat(g,id=2)])
        r=self.execute([{'path':str(p),'role':'hdmap','layer':'1_cross_outline_pl'}])
        self.assertEqual(r['totals']['output'],0);self.assertEqual(r['totals']['quarantined'],1)
        q=json.loads((self.root/'output/审核/隔离/hdmap_1_cross_outline_pl.json').read_text())
        self.assertEqual(q[0]['original_feature']['geometry'],g)

    def test_unknown_basis_fails_closed(self):
        p=self.source('ok.geojson',[feat(line())])
        r=self.execute([{'path':str(p),'role':'hdmap','layer':'2_cross_border_ln'}],coordinate_basis='gcj02')
        self.assertTrue(any(x['code']=='INPUT_READ_FAILED' for x in r['issues']))
        self.assertEqual(r['totals']['output'],0)

    def test_field_width_no_truncation(self):
        f=feat(line(),longvalue='汉'*100);f['id']='a'*24
        with self.assertRaisesRegex(ValueError,'254'):
            write_shp_zip(self.root/'bad.zip','bad',[f])
        self.assertFalse((self.root/'bad.zip').exists())

    def test_single_part_multipolygon_shp_roundtrip(self):
        g=polygon();g={'type':'MultiPolygon','coordinates':[g['coordinates']]}
        p=self.source('multi.geojson',[feat(g,LaneId='101',LaneEventDetectorCategoryId='2')])
        r=self.execute([{'path':str(p),'role':'detector','layer':'detector_A','intersection_id':'A'}])
        self.assertEqual(r['totals']['output'],1)
        self.assertFalse(any(x['code']=='SHP_EXPORT_FAILED' for x in r['issues']))
        self.assertTrue((self.root/'output/02_检测区/检测区合稿.zip').is_file())

    def test_repeated_ring_start_keeps_all_vertices(self):
        from hdmap_pipeline import exact_geometry_equal
        from shapely.geometry import shape
        g=polygon();g['coordinates'][0].insert(0,g['coordinates'][0][0])
        f=feat({'type':'MultiPolygon','coordinates':[g['coordinates']]},label='重复首点');f['id']='a'*24
        dest=self.root/'repeat.zip';write_shp_zip(dest,'repeat',[f])
        with zipfile.ZipFile(dest) as z:
            r=shapefile.Reader(shp=io.BytesIO(z.read('repeat/repeat.shp')),shx=io.BytesIO(z.read('repeat/repeat.shx')),dbf=io.BytesIO(z.read('repeat/repeat.dbf')))
            back=shape(r.shape(0).__geo_interface__)
        self.assertTrue(exact_geometry_equal(back,shape(f['geometry'])))
        self.assertEqual(len(back.exterior.coords),6)
        self.assertFalse(exact_geometry_equal(back,shape(polygon())))

    def test_second_run_does_not_overwrite(self):
        p=self.source('ok.geojson',[feat(line())]);self.execute([{'path':str(p),'role':'hdmap','layer':'2_cross_border_ln'}])
        before=(self.root/'output/checksums.sha256.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'already exists'):
            Pipeline(self.root/'manifest.json',self.root/'output').run()
        self.assertEqual(before,(self.root/'output/checksums.sha256.json').read_bytes())


if __name__=='__main__':
    unittest.main(verbosity=2)
