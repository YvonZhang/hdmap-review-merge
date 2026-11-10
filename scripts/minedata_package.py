#!/usr/bin/env python3
"""Package selected, already WGS84 2-D layers using the 2026-11-10 MineData layout.

No reprojection, schema rewriting, geometry repair, upload or business acceptance.
"""
import argparse
import codecs
import hashlib
import io
import json
import math
import re
import struct
import zipfile
from pathlib import Path, PurePosixPath

import shapefile
from pyproj import CRS
from shapely.geometry import shape
from shapely.validation import explain_validity

PROFILE = 'minedata_20261110_wgs84'
EXTENSIONS = ('.cpg', '.dbf', '.prj', '.qpj', '.shp', '.shx')
PRESERVED = ('.shp', '.shx', '.dbf', '.cpg')
WGS84 = CRS.from_epsg(4326)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def relevant(name):
    p = PurePosixPath(name)
    return '__MACOSX' not in p.parts and p.name != '.DS_Store' and not p.name.startswith('._')


def load_layer(path, member=None):
    """Read one selected SHP and companions without extracting the archive."""
    path = Path(path).resolve()
    if path.suffix.lower() == '.zip':
        raw = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            require(z.testzip() is None, f'CRC failure: {path}')
            infos = z.infolist()
            for item in infos:
                p = PurePosixPath(item.filename)
                require(not p.is_absolute() and '..' not in p.parts and '\\' not in item.filename,
                        f'Unsafe archive path: {item.filename}')
            names = [i.filename for i in infos if not i.is_dir() and relevant(i.filename)]
            require(len({n.casefold() for n in names}) == len(names), 'Duplicate ZIP entries')
            candidates = [n for n in names if n.lower().endswith('.shp')]
            if member is None:
                require(len(candidates) == 1, 'Select exactly one SHP; use input.member for a multi-layer ZIP')
                member = candidates[0]
            require(member in candidates, f'SHP member not found: {member}')
            stem = member[:-4]
            lookup = {n.casefold(): n for n in names}
            blobs = {ext: z.read(lookup[(stem + ext).casefold()]) for ext in EXTENSIONS
                     if (stem + ext).casefold() in lookup}
            meta = {'path': str(path), 'member': member, 'sha256': digest(raw),
                    'ignored_entries': [i.filename for i in infos if not relevant(i.filename)]}
    else:
        require(path.suffix.lower() == '.shp' and member is None, 'Inputs must be SHP or layer ZIP')
        companions = [p for p in path.parent.iterdir() if p.is_file() and p.stem.casefold() == path.stem.casefold()]
        lookup = {p.suffix.lower(): p for p in companions}
        require(len(lookup) == len(companions), 'Duplicate companion extensions')
        blobs = {ext: lookup[ext].read_bytes() for ext in EXTENSIONS if ext in lookup}
        meta = {'path': str(path), 'member': None}
    require(all(ext in blobs for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg')),
            f'Missing SHP/SHX/DBF/PRJ/CPG companions: {path}')
    meta['component_sha256'] = {ext: digest(data) for ext, data in blobs.items()}
    return blobs, meta


def check_wgs84(data, label):
    crs = CRS.from_user_input(data.decode('utf-8-sig').strip())
    require(crs.equals(WGS84, ignore_axis_order=True),
            f'{label} is not geographic WGS84/EPSG:4326; transform explicitly upstream, never relabel')


def inspect_blobs(blobs):
    check_wgs84(blobs['.prj'], 'PRJ')
    if '.qpj' in blobs:
        check_wgs84(blobs['.qpj'], 'QPJ')
    encoding = blobs['.cpg'].decode('ascii').strip()
    codec = codecs.lookup('utf-8' if encoding == '65001' else encoding).name
    require(codec == 'utf-8', 'This profile requires verified UTF-8; it does not transcode DBF')
    shp, shx, dbf = (blobs[ext] for ext in ('.shp', '.shx', '.dbf'))
    types = []
    for label, data in [('SHP', shp), ('SHX', shx)]:
        require(len(data) >= 100, f'{label} header truncated')
        require(struct.unpack_from('>i', data, 0)[0] == 9994, f'{label} file code')
        require(struct.unpack_from('>i', data, 24)[0] * 2 == len(data), f'{label} file length')
        require(struct.unpack_from('<i', data, 28)[0] == 1000, f'{label} version')
        types.append(struct.unpack_from('<i', data, 32)[0])
    require(types[0] == types[1] and types[0] in (3, 5),
            'This profile accepts 2-D PolyLine(3)/Polygon(5); resolve Z/M or other types upstream')
    require((len(shx) - 100) % 8 == 0, 'SHX index length')
    count = (len(shx) - 100) // 8
    offset = 100
    for n in range(count):
        require(offset + 12 <= len(shp), 'SHP record truncated')
        number, size_words = struct.unpack_from('>2i', shp, offset)
        index_offset, index_size = struct.unpack_from('>2i', shx, 100 + n * 8)
        require(number == n + 1 and index_offset * 2 == offset and index_size == size_words,
                f'SHP/SHX index mismatch at record {n + 1}')
        require(size_words >= 2 and offset + 8 + size_words * 2 <= len(shp), 'SHP record length')
        require(struct.unpack_from('<i', shp, offset + 8)[0] == types[0],
                f'Null or mixed shape at record {n + 1}')
        offset += 8 + size_words * 2
    require(offset == len(shp) and count > 0, 'SHP count/length mismatch or empty layer')
    require(len(dbf) >= 33, 'DBF header truncated')
    dbf_count, header_len, record_len = struct.unpack_from('<IHH', dbf, 4)
    require(dbf_count == count and header_len >= 33 and record_len > 1, 'DBF count/header mismatch')
    require(header_len <= len(dbf) and dbf[header_len - 1] == 13, 'DBF header terminator')
    end = header_len + record_len * count
    require(len(dbf) == end or (len(dbf) == end + 1 and dbf[-1] == 26), 'DBF data length')
    require(all(dbf[header_len + n * record_len] == 32 for n in range(count)), 'Deleted/invalid DBF record')
    reader = shapefile.Reader(shp=io.BytesIO(shp), shx=io.BytesIO(shx), dbf=io.BytesIO(dbf), encoding=codec)
    read_count = 0
    for sr in reader.iterShapeRecords():
        read_count += 1
        require(all(math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90
                    for x, y in sr.shape.points), f'Invalid lon/lat at record {read_count}')
        geom = shape(sr.shape.__geo_interface__)
        require(not geom.is_empty and geom.is_valid,
                f'Invalid geometry at record {read_count}: {explain_validity(geom)}')
    require(read_count == count, 'Reader count mismatch')
    return {'shape_type': types[0], 'upload_type': '线数据' if types[0] == 3 else '面数据',
            'features': count, 'valid_geometries': count, 'crs': 'EPSG:4326',
            'encoding': encoding, 'fields': [list(f) for f in reader.fields[1:]],
            'bbox': list(reader.bbox)}


def inspect_ready(path):
    """Validate the specific successful layout, not every possible MineData layout."""
    path = Path(path)
    blobs, meta = load_layer(path)
    stem = path.stem
    expected = {f'{stem}/': zipfile.ZIP_STORED}
    expected.update({f'{stem}/{stem}{ext}': zipfile.ZIP_STORED if ext == '.cpg' else zipfile.ZIP_DEFLATED
                     for ext in EXTENSIONS})
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        require(len(infos) == len(expected) and {i.filename for i in infos} == set(expected),
                f'Expected one same-name folder and six same-name files: {path.name}')
        require(all(i.compress_type == expected[i.filename] for i in infos), 'Compression differs from selected profile')
    stats = inspect_blobs(blobs)
    if stem.endswith(('_ln', '_pl')):
        require(stem.endswith('_ln' if stats['shape_type'] == 3 else '_pl'), 'Name/actual shape type mismatch')
    return {**meta, **stats, 'layout_profile': PROFILE, 'local_package_check': 'PASSED',
            'platform_import': 'NOT_TESTED_BY_SCRIPT', 'map_acceptance': 'NOT_ASSESSED'}


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value),
            f'Invalid output identifier: {value!r}')
    return value


def pack(manifest, output):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    require(not output.exists(), f'Output already exists: {output}')
    cfg = json.loads(manifest.read_text(encoding='utf-8'))
    require(cfg.get('profile') == PROFILE, f'Explicitly select profile {PROFILE}')
    for key in ('scope_note', 'basis_evidence', 'reference_evidence'):
        require(isinstance(cfg.get(key), str) and cfg[key].strip(), f'Missing {key}')
    require(cfg.get('coordinate_basis') == 'wgs84', 'Explicit WGS84 basis required')
    prefix = identifier(cfg['output_prefix'])
    base = manifest.parent
    sample, sample_meta = load_layer(base / cfg['reference_zip'])
    require('.qpj' in sample, 'Reference ZIP must contain verified PRJ and QPJ')
    inspect_blobs(sample)
    inputs = cfg.get('inputs')
    require(isinstance(inputs, list) and inputs, 'Explicit selected input list required')
    selected, names = [], set()
    for entry in inputs:
        layer = identifier(entry['layer'])
        stem = f'{prefix}_{layer}'
        require(stem.casefold() not in names, f'Output name collision: {stem}')
        names.add(stem.casefold())
        blobs, source = load_layer(base / entry['path'], entry.get('member'))
        stats = inspect_blobs(blobs)
        require(layer.endswith('_ln' if stats['shape_type'] == 3 else '_pl'),
                f'Layer suffix disagrees with actual SHP geometry: {layer}')
        selected.append((stem, blobs, source, stats))
    # All layers are validated before any output directory is created.
    output.mkdir(parents=True)
    target = output / 'SHP_ZIP'
    target.mkdir()
    reports = []
    for stem, source_blobs, source, stats in selected:
        blobs = {ext: source_blobs[ext] for ext in PRESERVED}
        blobs.update({ext: sample[ext] for ext in ('.prj', '.qpj')})
        dest = target / f'{stem}.zip'
        with zipfile.ZipFile(dest, 'x') as z:
            z.writestr(f'{stem}/', b'', compress_type=zipfile.ZIP_STORED)
            for ext in EXTENSIONS:
                z.writestr(f'{stem}/{stem}{ext}', blobs[ext],
                           compress_type=zipfile.ZIP_STORED if ext == '.cpg' else zipfile.ZIP_DEFLATED)
        checked = inspect_ready(dest)
        verified, _ = load_layer(dest)
        require(all(verified[ext] == source_blobs[ext] for ext in PRESERVED), 'Preserved component bytes changed')
        reports.append({**checked, 'source': source, 'dataset_name': stem,
                        'preserved_bytes': list(PRESERVED), 'crs_metadata_reference': sample_meta})
    save(output / 'manifest.used.json', cfg)
    summary = {'profile': PROFILE, 'scope_note': cfg['scope_note'],
               'manifest_path': str(manifest), 'manifest_sha256': digest(manifest.read_bytes()),
               'layers': len(reports), 'features': sum(r['features'] for r in reports),
               'local_package_check': 'PASSED', 'platform_import': 'NOT_TESTED_BY_SCRIPT',
               'map_acceptance': 'NOT_ASSESSED', 'files': reports}
    save(output / 'packaging_audit.json', summary)
    return {k: v for k, v in summary.items() if k != 'files'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    pack_cmd = sub.add_parser('pack', help='Repackage explicitly selected WGS84 2-D layers')
    pack_cmd.add_argument('--manifest', required=True, type=Path)
    pack_cmd.add_argument('--output', required=True, type=Path)
    inspect_cmd = sub.add_parser('inspect', help='Check selected final ZIPs against this layout')
    inspect_cmd.add_argument('zip', nargs='+', type=Path)
    inspect_cmd.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'pack':
            result = pack(args.manifest, args.output)
        else:
            require(args.report is None or not args.report.exists(), 'Report already exists')
            rows = [inspect_ready(p) for p in args.zip]
            result = {'layers': len(rows), 'features': sum(r['features'] for r in rows), 'files': rows}
            if args.report:
                save(args.report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, shapefile.ShapefileException) as exc:
        parser.exit(1, f'MineData packaging stopped: {exc}\n')


if __name__ == '__main__':
    main()
