"""Run with HDMAP_TEST_DIR set to a project-local process directory."""
import copy
import io
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

import shapefile
from pyproj import CRS

import minedata_package as m


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['HDMAP_TEST_DIR'])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        buffers = {ext: io.BytesIO() for ext in ('.shp', '.shx', '.dbf')}
        writer = shapefile.Writer(shp=buffers['.shp'], shx=buffers['.shx'], dbf=buffers['.dbf'],
                                  shapeType=3, encoding='utf-8')
        writer.field('name', 'C', 40)
        writer.field('FID', 'N', 18, 0)
        writer.line([[[114.9, 40.8], [114.91, 40.81]]])
        writer.record('中文路口', 17)
        writer.close()
        self.blobs = {ext: buf.getvalue() for ext, buf in buffers.items()}
        self.blobs.update({'.cpg': b'UTF-8', '.prj': m.WGS84.to_wkt(version='WKT1_ESRI').encode(),
                           '.qpj': m.WGS84.to_wkt(version='WKT1_GDAL').encode()})
        self.write_zip('reference.zip', self.blobs)
        self.write_zip('input.zip', self.blobs, extra=True)
        self.cfg = {'profile': m.PROFILE, 'scope_note': 'synthetic fixture', 'coordinate_basis': 'wgs84',
                    'basis_evidence': 'explicit synthetic WGS84 points', 'reference_evidence': 'test fixture',
                    'reference_zip': 'reference.zip', 'output_prefix': 'test_20261110',
                    'inputs': [{'path': 'input.zip', 'layer': '2_cross_border_ln'}]}

    def write_zip(self, name, blobs, extra=False):
        with zipfile.ZipFile(self.root / name, 'w') as z:
            for ext, data in blobs.items():
                z.writestr('source/source' + ext, data)
            if extra:
                z.writestr('__MACOSX/._source', b'ignored metadata')
                z.writestr('.DS_Store', b'ignored metadata')

    def run_pack(self):
        path = self.root / 'manifest.json'
        m.save(path, self.cfg)
        return m.pack(path, self.root / 'output')

    def rejected(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.run_pack()
        self.assertFalse((self.root / 'output').exists())

    def test_roundtrip_preserves_chinese_fields_and_removes_metadata(self):
        result = self.run_pack()
        self.assertEqual(result['features'], 1)
        dest = next((self.root / 'output/SHP_ZIP').glob('*.zip'))
        actual, _ = m.load_layer(dest)
        self.assertEqual(actual, self.blobs)
        self.assertEqual(m.inspect_ready(dest)['fields'], [['name', 'C', 40, 0], ['FID', 'N', 18, 0]])
        self.assertEqual(result['platform_import'], 'NOT_TESTED_BY_SCRIPT')

    def test_projected_crs_cannot_be_relabelled(self):
        self.blobs['.prj'] = CRS.from_epsg(3857).to_wkt().encode()
        self.write_zip('input.zip', self.blobs)
        self.rejected('not geographic WGS84')

    def test_missing_prj_stops_before_output(self):
        del self.blobs['.prj']
        self.write_zip('input.zip', self.blobs)
        self.rejected('Missing SHP/SHX/DBF/PRJ/CPG')

    def test_qpj_cannot_disagree_with_prj(self):
        self.blobs['.qpj'] = CRS.from_epsg(4490).to_wkt().encode()
        self.write_zip('input.zip', self.blobs)
        self.rejected('QPJ is not geographic WGS84')

    def test_z_geometry_is_not_silently_dropped(self):
        for ext in ('.shp', '.shx'):
            data = bytearray(self.blobs[ext])
            struct.pack_into('<i', data, 32, 13)
            self.blobs[ext] = bytes(data)
        self.write_zip('input.zip', self.blobs)
        self.rejected('2-D PolyLine')

    def test_type_is_not_inferred_from_layer_name(self):
        self.cfg['inputs'][0]['layer'] = '12_crosswalk_line_pl'
        self.rejected('suffix disagrees')

    def test_duplicate_output_names_stop_before_write(self):
        self.cfg['inputs'].append(copy.deepcopy(self.cfg['inputs'][0]))
        self.rejected('name collision')

    def test_shx_offset_is_checked(self):
        data = bytearray(self.blobs['.shx'])
        struct.pack_into('>i', data, 100, 51)
        self.blobs['.shx'] = bytes(data)
        self.write_zip('input.zip', self.blobs)
        self.rejected('SHP/SHX index mismatch')

    def test_existing_output_is_preserved(self):
        out = self.root / 'output'
        out.mkdir()
        marker = out / 'original.txt'
        marker.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            self.run_pack()
        self.assertEqual(marker.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
