#!/usr/bin/env python3
"""Audit and assemble explicitly selected 2-D HD-map/detector inputs. Never edits inputs."""
import argparse
import collections
import copy
import csv
import hashlib
import html
import io
import json
import math
import re
import shutil
import sys
import zipfile
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import shape, mapping
from shapely.geometry.polygon import orient
from shapely.ops import transform
from shapely.validation import explain_validity

WGS84 = CRS.from_epsg(4326)
CATEGORY = 'LaneEventDetectorCategoryId'
CHANGED = {'6_laneline_W_ln', '7_laneline_Y_ln', '9_lane_stop_line_ln',
           '12_crosswalk_line_ln', '17_bus_turnout_line_ln',
           '21_no_parking_area_ln', '23_turn_waiting_area_line_ln'}


def dump(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def resolve(base, p):
    return (base / p).resolve()


def family(g):
    return g.geom_type.removeprefix('Multi')


def positions(coords):
    if not isinstance(coords, (list, tuple)) or not coords:
        return
    if isinstance(coords[0], (float, int)):
        yield coords
    else:
        for c in coords:
            yield from positions(c)


def oriented(g, ccw=True):
    if g.geom_type == 'Polygon':
        return orient(g, sign=1.0 if ccw else -1.0)
    if g.geom_type == 'MultiPolygon':
        from shapely.geometry import MultiPolygon
        return MultiPolygon([orient(p, sign=1.0 if ccw else -1.0) for p in g.geoms])
    return g


def exact_geometry_equal(a, b):
    # SHP does not distinguish a single Polygon/LineString from a one-part Multi.
    # Promote both representations, then compare every coordinate with zero tolerance.
    from shapely.geometry import MultiPolygon, MultiLineString
    def promote(g):
        if g.geom_type == 'Polygon':
            return MultiPolygon([g])
        if g.geom_type == 'LineString':
            return MultiLineString([g])
        return g
    a, b = promote(a), promote(b)
    # GEOS normalize may choose different ring starts when the minimum vertex
    # occurs twice consecutively. Compare cyclic sequences, preserving every
    # vertex occurrence; this is still exact, not a topology-only comparison.
    def ring(coords):
        pts = tuple(tuple(p) for p in coords)[:-1]
        if not pts:
            return ()
        candidates = []
        for seq in (pts, tuple(reversed(pts))):
            smallest = min(seq)
            for i, p in enumerate(seq):
                if p == smallest:
                    candidates.append(seq[i:]+seq[:i])
        return min(candidates)
    def signature(g):
        if g.geom_type == 'Polygon':
            return (ring(g.exterior.coords), tuple(sorted(ring(r.coords) for r in g.interiors)))
        if g.geom_type == 'MultiPolygon':
            return tuple(sorted(signature(p) for p in g.geoms))
        if g.geom_type == 'LineString':
            pts=tuple(tuple(p) for p in g.coords)
            return min(pts,tuple(reversed(pts)))
        if g.geom_type == 'MultiLineString':
            return tuple(sorted(signature(p) for p in g.geoms))
        return tuple(g.coords)
    return a.geom_type == b.geom_type and signature(a) == signature(b)


def read_source(entry, base):
    """Return original properties and geometries plus source CRS and byte hashes."""
    path = resolve(base, entry['path'])
    raw = path.read_bytes()
    meta = {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}
    if path.suffix.lower() in ('.geojson', '.json'):
        def invalid_constant(value):
            raise ValueError('Non-standard JSON numeric constant: ' + value)
        d = json.loads(raw.decode('utf-8-sig'), parse_constant=invalid_constant)
        if d.get('type') != 'FeatureCollection' or not isinstance(d.get('features'), list):
            raise ValueError('GeoJSON input must be a FeatureCollection')
        declared = (d.get('crs') or {}).get('properties', {}).get('name')
        crs = CRS.from_user_input(entry.get('crs_override') or declared or 'OGC:CRS84')
        meta['crs_evidence'] = 'manifest override' if entry.get('crs_override') else ('GeoJSON crs' if declared else 'RFC7946 default; coordinate basis separately declared in manifest')
        fs = d['features']
        for f in fs:
            if f.get('type') != 'Feature' or not isinstance(f.get('properties'), (dict, type(None))):
                raise ValueError('Malformed Feature or properties')
        return fs, crs, meta
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if not n.endswith('/') and not n.startswith('__MACOSX/')]
            candidates = [n for n in names if n.lower().endswith('.shp')]
            member = entry.get('member')
            if member:
                if member not in candidates:
                    raise ValueError('Specified SHP member not found')
            elif len(candidates) == 1:
                member = candidates[0]
            else:
                raise ValueError('ZIP must contain one SHP, or select an explicit member')
            stem = member[:-4]
            blobs = {}
            for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
                matches = [n for n in names if n.casefold() == (stem + ext).casefold()]
                if len(matches) > 1:
                    raise ValueError('Duplicate ZIP sidecar name')
                if matches:
                    blobs[ext] = z.read(matches[0])
            meta['member'] = member
    elif path.suffix.lower() == '.shp':
        blobs = {}
        for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            matches = [p for p in path.parent.iterdir() if p.stem.casefold() == path.stem.casefold() and p.suffix.casefold() == ext]
            if len(matches) > 1:
                raise ValueError('Ambiguous sidecar filename')
            if matches:
                blobs[ext] = matches[0].read_bytes()
    else:
        raise ValueError('Supported inputs: .geojson/.json FeatureCollection, .shp, one-layer .zip')
    missing = {'.shp', '.shx', '.dbf'} - blobs.keys()
    if missing:
        raise ValueError('Missing SHP sidecars: ' + ','.join(sorted(missing)))
    crs_text = entry.get('crs_override') or blobs.get('.prj', b'').decode('utf-8-sig').strip()
    if not crs_text:
        raise ValueError('Missing PRJ; require an evidenced crs_override')
    encoding = entry.get('encoding') or blobs.get('.cpg', b'').decode('ascii').strip()
    encoding = {'65001': 'utf-8', '936': 'gbk'}.get(encoding, encoding)
    if not encoding:
        raise ValueError('Missing CPG; declare verified encoding in manifest')
    meta.update({'sidecars': {k: sha(v) for k, v in blobs.items()}, 'encoding': encoding,
                 'crs_evidence': 'manifest override' if entry.get('crs_override') else '.prj'})
    r = shapefile.Reader(shp=io.BytesIO(blobs['.shp']), shx=io.BytesIO(blobs['.shx']),
                         dbf=io.BytesIO(blobs['.dbf']), encoding=encoding, encodingErrors='strict')
    if r.shapeType not in (0, 1, 3, 5, 8):
        raise ValueError('Only 2-D SHP supported; Z/M inputs require an explicit lossless workflow')
    if len(r.shapes()) != r.numRecords:
        raise ValueError('SHP and DBF record counts disagree')
    names = [f[0] for f in r.fields[1:]]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate DBF field names')
    meta['fields'] = [list(f) for f in r.fields[1:]]
    fs = []
    for sr in r.iterShapeRecords():
        props = sr.record.as_dict()
        for k, v in props.items():
            if hasattr(v, 'isoformat'):
                props[k] = v.isoformat()
        fs.append({'type': 'Feature', 'properties': props,
                   'geometry': None if sr.shape.shapeType == 0 else sr.shape.__geo_interface__})
    if len(fs) != r.numRecords:
        raise ValueError('Deleted DBF records detected; resolve explicitly before merging')
    return fs, CRS.from_user_input(crs_text), meta


def dbf_text(v):
    if v is None:
        return ''
    return v if isinstance(v, str) else compact(v)


def write_shp_zip(dest, stem, features):
    """SHP is a companion export; full attribute types remain authoritative in GeoJSON."""
    geoms = [shape(f['geometry']) for f in features]
    kinds = {family(g) for g in geoms}
    if len(kinds) != 1 or next(iter(kinds)) not in ('Point', 'LineString', 'Polygon'):
        raise ValueError('SHP export requires one compatible geometry family')
    kind = next(iter(kinds))
    if kind == 'Point' and any(g.geom_type == 'MultiPoint' for g in geoms):
        raise ValueError('MultiPoint SHP export is outside this 2-D road-layer workflow')
    fields = sorted({k for f in features for k in f['properties']})
    if len(fields) > 240:
        raise ValueError('Too many DBF fields; use GeoJSON')
    aliases, used = {}, {'audituid'}
    preferred = {'LaneId': 'LaneId', CATEGORY: 'DetCat', 'IntersectionId': 'InterId'}
    specs = []
    for n, key in enumerate(fields):
        candidate = preferred.get(key, key)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,9}', candidate) or candidate.casefold() in used:
            candidate = f'F{n:08d}'
        used.add(candidate.casefold())
        vals = [f['properties'].get(key) for f in features]
        nonnull = [v for v in vals if v is not None]
        if nonnull and all(isinstance(v, bool) for v in nonnull):
            spec = (candidate, 'L', 1, 0)
        elif nonnull and all(isinstance(v, int) and not isinstance(v, bool) for v in nonnull) and max(len(str(v)) for v in nonnull) <= 18:
            spec = (candidate, 'N', 18, 0)
        else:
            # Floats use lossless decimal strings; avoid silent fixed-decimal rounding.
            width = max([1] + [len(dbf_text(v).encode('utf-8')) for v in vals])
            if width > 254:
                raise ValueError(f'Field {key} exceeds 254 UTF-8 bytes; would truncate DBF')
            spec = (candidate, 'C', width, 0)
        specs.append((key, spec))
        aliases[key] = {'dbf_name': candidate, 'dbf_type': spec[1],
                        'source_types': sorted({type(v).__name__ for v in nonnull})}
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType={'Point': 1, 'LineString': 3, 'Polygon': 5}[kind], encoding='utf-8')
    w.field('AuditUid', 'C', 24)
    for key, spec in specs:
        w.field(*spec)
    for f, g in zip(features, geoms):
        w.shape(mapping(oriented(g, ccw=False)))
        w.record(f['id'], *[dbf_text(f['properties'].get(key)) if spec[1] == 'C' else f['properties'].get(key) for key, spec in specs])
    w.close()
    blobs = {'.shp': shp.getvalue(), '.shx': shx.getvalue(), '.dbf': dbf.getvalue(),
             '.prj': WGS84.to_wkt(version='WKT1_ESRI').encode(), '.cpg': b'UTF-8'}
    # Read the exact exported bytes before packaging.
    rr = shapefile.Reader(shp=io.BytesIO(blobs['.shp']), shx=io.BytesIO(blobs['.shx']), dbf=io.BytesIO(blobs['.dbf']), encoding='utf-8')
    if len(rr) != len(features):
        raise ValueError('SHP readback count mismatch')
    for sr, f, g in zip(rr.iterShapeRecords(), features, geoms):
        if not exact_geometry_equal(shape(sr.shape.__geo_interface__), g):
            raise ValueError('SHP geometry changed during round trip')
        rec = sr.record.as_dict()
        if rec['AuditUid'] != f['id']:
            raise ValueError('SHP UID round trip failed')
        for key, spec in specs:
            expected = dbf_text(f['properties'].get(key)).strip() if spec[1] == 'C' else f['properties'].get(key)
            if rec[spec[0]] != expected:
                raise ValueError(f'DBF readback mismatch: {key}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for ext, blob in blobs.items():
            z.writestr(f'{stem}/{stem}{ext}', blob)
    return aliases


class Pipeline:
    def __init__(self, manifest_path, output):
        self.manifest_path = manifest_path.resolve()
        self.base = self.manifest_path.parent
        self.cfg = json.loads(manifest_path.read_text())
        if self.cfg.get('profile') not in ('spec20241118', 'legacy2023'):
            raise ValueError('Select profile spec20241118 or legacy2023 explicitly')
        self.out = output.resolve()
        self.issues, self.sources, self.ledger = [], [], []
        self.groups, self.quarantine = collections.defaultdict(list), collections.defaultdict(list)
        self.stats, self.geoms = {}, {}
        self.seen, self.geom_seen, self.detkeys = {}, {}, {}

    def issue(self, severity, code, group='', source='', row='', detail='', **extra):
        self.issues.append(dict(severity=severity, code=code, layer=group, source=source, row=row, detail=detail, **extra))

    def run(self):
        if self.out.exists():
            raise ValueError('Output already exists; choose a fresh directory')
        entries = self.cfg.get('inputs', [])
        if not entries:
            raise ValueError('Manifest inputs are empty')
        for e in entries:
            p = resolve(self.base, e['path'])
            if self.out == p or self.out in p.parents:
                raise ValueError('Output must not contain any input source')
            if e.get('role') not in ('hdmap', 'detector'):
                raise ValueError('Each input must specify role hdmap/detector')
            if not re.fullmatch(r'[A-Za-z0-9_\-]+', e.get('layer', '')):
                raise ValueError('Explicit safe canonical layer name required')
        self.out.mkdir(parents=True)
        dump(self.out/'manifest.used.json', self.cfg)
        for index, e in enumerate(entries):
            print(f'Reading {index + 1}/{len(entries)}: {e["layer"]}', flush=True)
            self.ingest(e, index)
        self.check_detector_pairs()
        self.check_detector_geometry()
        self.check_profile()
        self.write_layers()
        self.write_styles()
        self.issue('review', 'MANUAL_ACCURACY', detail='10 cm / 1 m accuracy needs contemporaneous survey control or verified imagery; vector topology is not survey accuracy.')
        self.issue('review', 'MANUAL_COVERAGE', detail='250 m bidirectional coverage, junction completeness and seams require an authoritative junction list and field/imagery review. Folder prefixes are not coverage evidence.')
        if any(e['role'] == 'detector' for e in entries):
            self.issue('review', 'MANUAL_DETECTOR_POSITION', detail='Check only motor lanes, actual travel direction, stop-line crossing, ~60 m along-lane position, ~5 m travel length and EOC lane matching. Nearest-stop-line distance alone is insufficient.')
        counts = collections.Counter(i['severity'] for i in self.issues)
        totals = {k: sum(v[k] for v in self.stats.values()) for k in ('input', 'output', 'deduplicated', 'quarantined')}
        if totals['input'] != totals['output'] + totals['deduplicated'] + totals['quarantined']:
            raise AssertionError('Feature conservation failed')
        audit = {'status': 'BLOCKED' if counts['error'] else 'REVIEW_REQUIRED', 'approved_for_release': False,
                 'profile': self.cfg.get('profile'), 'totals': totals, 'issue_counts': dict(counts),
                 'layers': self.stats, 'sources': self.sources, 'issues': self.issues,
                 'input_scope': self.cfg.get('scope_note'), 'selection_notes': self.cfg.get('selection_notes', [])}
        dump(self.out/'审核/audit.json', audit)
        dump(self.out/'审核/provenance.json', self.ledger)
        self.write_csv()
        self.write_report(audit)
        checksums = {str(p.relative_to(self.out)): sha(p.read_bytes()) for p in sorted(self.out.rglob('*')) if p.is_file()}
        dump(self.out/'checksums.sha256.json', checksums)
        print(json.dumps({'output': str(self.out), 'status': audit['status'], 'totals': totals, 'issues': dict(counts)}, ensure_ascii=False))
        return audit

    def ingest(self, e, index):
        role, layer = e['role'], e['layer']
        group = f'{role}/{layer}'
        source_id = f's{index + 1:03d}'
        stat = self.stats.setdefault(group, {'role': role, 'layer': layer, 'input': 0, 'output': 0,
                                         'deduplicated': 0, 'quarantined': 0, 'source_ids': [], 'geometry_types': {}, 'files': {}})
        stat['source_ids'].append(source_id)
        try:
            basis = e.get('coordinate_basis', self.cfg.get('coordinate_basis'))
            if basis != 'wgs84':
                raise ValueError('Require evidenced coordinate_basis=wgs84; GCJ02/BD09/unknown cannot be relabelled or automatically converted')
            if re.search(r'gcj|gcl02|84_to_02|mapshepered_02', e['path'], re.I):
                raise ValueError('Source path indicates offset-coordinate processing; resolve datum evidence first')
            fs, crs, meta = read_source(e, self.base)
        except Exception as ex:
            self.issue('error', 'INPUT_READ_FAILED', group, source_id, detail=str(ex))
            self.sources.append({'source_id': source_id, 'path': str(resolve(self.base, e['path'])), 'error': str(ex)})
            return
        meta.update({'source_id': source_id, 'role': role, 'layer': layer, 'input_features': len(fs),
                     'crs': crs.to_string(), 'original_path': e.get('original_path'), 'intersection_id': e.get('intersection_id'), 'basis_evidence': e.get('basis_evidence', self.cfg.get('basis_evidence', 'manifest declaration'))})
        self.sources.append(meta)
        if role == 'detector' and not e.get('intersection_id') and any(not (f.get('properties') or {}).get('IntersectionId') for f in fs):
            self.issue('review', 'INTERSECTION_ID_UNVERIFIED', group, source_id, detail='Uses local dataset key; match official junction registry before deployment')
        if not crs.equals(WGS84, ignore_axis_order=True):
            self.issue('info', 'CRS_TRANSFORMED', group, source_id, detail=f'{crs.to_string()} -> EPSG:4326 using declared CRS and always_xy=True')
        transformer = Transformer.from_crs(crs, WGS84, always_xy=True)
        attr_empty = collections.Counter()
        for row, original in enumerate(fs, 1):
            stat['input'] += 1
            uid = sha(f'{source_id}:{meta["sha256"]}:{row}'.encode())[:24]
            props = copy.deepcopy(original.get('properties') or {})
            f = {'type': 'Feature', 'id': uid, 'properties': props, 'geometry': original.get('geometry')}
            log = {'uid': uid, 'source_id': source_id, 'source_row_1based': row,
                   'original_feature_id': original.get('id'), 'group': group, 'disposition': 'output'}
            self.ledger.append(log)
            errors_before = sum(i['severity'] == 'error' for i in self.issues) if role == 'detector' else 0
            try:
                rawgeom = f['geometry']
                if rawgeom is None:
                    raise ValueError('NULL geometry')
                pos = list(positions(rawgeom.get('coordinates', [])))
                if not pos or any(len(p) != 2 or not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in p) for p in pos):
                    raise ValueError('Require finite 2-D positions; Z/M/GeometryCollection require a separate workflow')
                rings = rawgeom.get('coordinates', []) if rawgeom.get('type') == 'Polygon' else [r for poly in rawgeom.get('coordinates', []) for r in poly] if rawgeom.get('type') == 'MultiPolygon' else []
                if any(len(r) < 4 or list(r[0]) != list(r[-1]) for r in rings):
                    raise ValueError('Polygon ring must have at least 4 positions and be explicitly closed')
                g = shape(rawgeom)
                if g.is_empty:
                    raise ValueError('Empty geometry')
                if not g.is_valid:
                    raise ValueError(explain_validity(g))
                if not crs.equals(WGS84, ignore_axis_order=True):
                    g = transform(transformer.transform, g)
                if not g.is_valid or not all(math.isfinite(v) for v in g.bounds):
                    raise ValueError('Invalid geometry after projection')
                xmin, ymin, xmax, ymax = g.bounds
                if not (-180 <= xmin <= xmax <= 180 and -90 <= ymin <= ymax <= 90):
                    raise ValueError('WGS84 coordinates out of range; check axis order and CRS')
                expected = self.cfg.get('expected_bbox')
                if expected and not (expected[0] <= xmin <= xmax <= expected[2] and expected[1] <= ymin <= ymax <= expected[3]):
                    raise ValueError('Outside manifest project bounding box')
                wanted = 'Polygon' if role == 'detector' or layer.endswith('_pl') else 'LineString'
                if family(g) != wanted:
                    raise ValueError(f'Layer expects {wanted}, actual {g.geom_type}')
                g = oriented(g)
                f['geometry'] = mapping(g)
                compact(props)  # reject non-finite or non-JSON attribute values
            except Exception as ex:
                self.issue('error', 'GEOMETRY_OR_VALUE_INVALID', group, source_id, row, str(ex))
                stat['quarantined'] += 1
                log['disposition'] = 'quarantined'
                # Preserve original geometry verbatim; this quarantine is not a compliant dataset.
                self.quarantine[group].append({'source_id': source_id, 'row': row, 'uid': uid, 'reason': str(ex), 'original_feature': original})
                continue
            if role == 'detector':
                self.normalize_detector(e, props, group, source_id, row)
                if sum(i['severity'] == 'error' for i in self.issues) > errors_before:
                    stat['quarantined'] += 1
                    log['disposition'] = 'quarantined'
                    self.quarantine[group].append({'source_id': source_id, 'row': row, 'uid': uid, 'reason': 'Detector attributes invalid; see issues', 'original_feature': original})
                    continue
            for key in ('id', 'width', 'color'):
                if key in props and props[key] in (None, '', 0, '0'):
                    attr_empty[key] += 1
            content = g.normalize().wkb + compact(props).encode()
            fingerprint = sha(content)
            duplicate_key = (group, fingerprint)
            if duplicate_key in self.seen and self.cfg.get('deduplicate_exact', False):
                stat['deduplicated'] += 1
                log.update({'disposition': 'deduplicated', 'kept_uid': self.seen[duplicate_key]})
                continue
            if duplicate_key in self.seen:
                self.issue('review', 'EXACT_DUPLICATE_RETAINED', group, source_id, row, self.seen[duplicate_key])
            self.seen.setdefault(duplicate_key, uid)
            geometry_key = (group, sha(g.normalize().wkb))
            if geometry_key in self.geom_seen and self.geom_seen[geometry_key][0] != fingerprint:
                self.issue('review', 'SAME_GEOMETRY_DIFFERENT_ATTRIBUTES', group, source_id, row,
                           f'Kept both; compare {self.geom_seen[geometry_key][1]} and {uid}')
            self.geom_seen.setdefault(geometry_key, (fingerprint, uid))
            if role == 'detector':
                key = (props['IntersectionId'], props['LaneId'], props[CATEGORY])
                if key in self.detkeys:
                    self.issue('error', 'DETECTOR_KEY_CONFLICT', group, source_id, row,
                               f'Composite key {key} repeated; existing UID {self.detkeys[key]}; retained for review')
                self.detkeys.setdefault(key, uid)
            self.groups[group].append(f)
            self.geoms[uid] = g
            stat['output'] += 1
            stat['geometry_types'][g.geom_type] = stat['geometry_types'].get(g.geom_type, 0) + 1
        if role == 'hdmap':
            for key, count in attr_empty.items():
                self.issue('review', 'ATTRIBUTE_EMPTY_OR_ZERO', group, source_id, detail=f'{key}: {count} empty/zero values; no attributes invented')

    def normalize_detector(self, e, props, group, source, row):
        for old, canonical in e.get('field_map', {}).items():
            if old in props:
                if canonical in props and str(props[canonical]) != str(props[old]):
                    self.issue('error', 'FIELD_ALIAS_CONFLICT', group, source, row, f'{old} != {canonical}')
                else:
                    props[canonical] = props[old]
        for key in ('LaneId', CATEGORY):
            if key not in props or props[key] is None:
                self.issue('error', 'DETECTOR_FIELD_MISSING', group, source, row, key)
        lane, cat = str(props.get('LaneId', '')).strip(), str(props.get(CATEGORY, '')).strip()
        if not re.fullmatch(r'[1-9][01][1-9]', lane):
            self.issue('error', 'LANE_ID_INVALID', group, source, row, f'LaneId={lane}; requires direction 1-9, in/out 0/1, lane 1-9')
        if cat not in ('1', '2', '3', '4'):
            self.issue('error', 'DETECTOR_CATEGORY_INVALID', group, source, row, cat)
        elif len(lane) == 3 and lane[1] != ('0' if cat in ('1', '2') else '1'):
            self.issue('error', 'DETECTOR_DIRECTION_CONFLICT', group, source, row, f'LaneId={lane}, category={cat}')
        inter = e.get('intersection_id') or props.get('IntersectionId')
        if e.get('intersection_id') and props.get('IntersectionId') and str(e['intersection_id']) != str(props['IntersectionId']):
            self.issue('error', 'INTERSECTION_ID_CONFLICT', group, source, row, 'Manifest and property IntersectionId differ')
        if not inter:
            inter = 'local:' + group.split('/')[-1]
        props.update({'LaneId': lane, CATEGORY: cat, 'IntersectionId': str(inter)})

    def check_detector_pairs(self):
        keys = set(self.detkeys)
        for inter, lane, cat in sorted(keys):
            other = {'1': '2', '2': '1', '3': '4', '4': '3'}[cat]
            if (inter, lane, other) not in keys:
                self.issue('review', 'DETECTOR_PAIR_MISSING', 'detector', detail=f'{inter} lane {lane}: category {cat} exists, {other} missing. Widening/slip lanes may need an approved exception.')

    def check_profile(self):
        if self.cfg.get('profile') == 'spec20241118':
            for group in self.stats:
                layer = group.split('/')[-1]
                if layer in CHANGED:
                    self.issue('error', 'SPEC_REQUIRES_POLYGON', group, detail=f'2024-11-18 requires {layer[:-2]}pl. Historical line geometry retained; no filename-only conversion or arbitrary buffer.')
            if 'hdmap/26_channelization_ln' in self.stats:
                self.issue('review', 'SPEC_TEXT_CONFLICT', 'hdmap/26_channelization_ln', detail='Document names _ln and says polygon while describing individual marking centre lines; resolve with owner. Waiting-area attribute table also still says Line despite polygon change.')
        if self.cfg.get('expected_layers'):
            found = {s['layer'] for s in self.stats.values() if s['output']}
            for layer in sorted(set(self.cfg['expected_layers']) - found):
                self.issue('error', 'EXPECTED_LAYER_MISSING', layer, detail='Required by manifest expected_layers; absent/empty after validation')

    def check_detector_geometry(self):
        from shapely.ops import unary_union
        detectors = [(group, f) for group, fs in self.groups.items() if group.startswith('detector/') for f in fs]
        if not detectors:
            return
        bounds = [self.geoms[f['id']].bounds for _, f in detectors]
        longitude = sum((b[0]+b[2])/2 for b in bounds)/len(bounds)
        latitude = sum((b[1]+b[3])/2 for b in bounds)/len(bounds)
        zone = max(1, min(60, int((longitude+180)//6)+1))
        local = Transformer.from_crs(WGS84, (32600 if latitude >= 0 else 32700)+zone, always_xy=True)
        metric = {f['id']: transform(local.transform, self.geoms[f['id']]) for _,f in detectors}
        outlines = [transform(local.transform, self.geoms[f['id']]) for g,fs in self.groups.items() if g.endswith('/1_cross_outline_pl') for f in fs]
        road = unary_union(outlines) if outlines else None
        pairs = {}
        for group, f in detectors:
            geom = metric[f['id']]
            coords = list(geom.minimum_rotated_rectangle.exterior.coords)
            sides = [math.dist(coords[i], coords[i+1]) for i in range(4)]
            short, long = min(sides), max(sides)
            if not any(3 <= v <= 7 for v in (short, long)) or short < 1 or long > 15:
                self.issue('review', 'DETECTOR_SIZE_SCREEN', group, detail=f'UID {f["id"]}: minimum rectangle {short:.2f} × {long:.2f} m. Approximate screen only; actual travel-axis length must be ~5 m.')
            if road is not None:
                area = geom.difference(road).area
                if area > 1:
                    self.issue('review', 'DETECTOR_OUTSIDE_ROAD', group, detail=f'UID {f["id"]}: {area:.2f} m² outside selected valid road-outline union; check source version, datum and geometry.')
            p=f['properties']; pairs.setdefault((p['IntersectionId'],p['LaneId']),{})[p[CATEGORY]]=(f['id'],geom)
        for (inter,lane), cats in pairs.items():
            for first, second in [('1','2'),('3','4')]:
                if first in cats and second in cats:
                    distance=cats[first][1].centroid.distance(cats[second][1].centroid)
                    if distance < 30 or distance > 90:
                        self.issue('review','DETECTOR_DISTANCE_SCREEN','detector',detail=f'{inter} lane {lane}, categories {first}/{second}: centroid straight-line distance {distance:.2f} m; 30–90 m is a screening range, not acceptance tolerance for the ~60 m along-lane rule.')

    def write_layers(self):
        prefix = self.cfg.get('output_prefix', 'merged')
        if not re.fullmatch(r'[A-Za-z0-9_\-]+', prefix):
            raise ValueError('Invalid output_prefix')
        for group, stat in self.stats.items():
            fs = self.groups[group]
            role, layer = group.split('/')
            root = self.out / ('01_高精地图' if role == 'hdmap' else '02_检测区')
            stem = f'{prefix}_{layer}'
            if fs:
                p = root/'GeoJSON'/f'{stem}.geojson'
                dump(p, {'type': 'FeatureCollection', 'features': fs})
                check = json.loads(p.read_text())
                if len(check['features']) != len(fs):
                    raise AssertionError('GeoJSON readback mismatch')
                stat['files']['geojson'] = str(p.relative_to(self.out))
                try:
                    q = root/'SHP_ZIP'/f'{stem}.zip'
                    fieldmap = write_shp_zip(q, stem, fs)
                    stat['files']['shp_zip'] = str(q.relative_to(self.out))
                    dump(root/'字段映射'/f'{stem}.json', {'fields': fieldmap, 'AuditUid': 'GeoJSON Feature.id; see 审核/provenance.json', 'null_and_string_note': 'DBF string null/empty and surrounding whitespace are not lossless; authoritative properties remain in GeoJSON.'})
                except Exception as ex:
                    self.issue('error', 'SHP_EXPORT_FAILED', group, detail=str(ex))
            if self.quarantine[group]:
                dump(self.out/'审核/隔离'/f'{role}_{layer}.json', self.quarantine[group])
        detectors = [f for group, fs in self.groups.items() if group.startswith('detector/') for f in fs]
        if detectors:
            dump(self.out/'02_检测区/检测区合稿.geojson', {'type': 'FeatureCollection', 'features': detectors})
            try:
                fieldmap = write_shp_zip(self.out/'02_检测区/检测区合稿.zip', 'detectors_merged', detectors)
                dump(self.out/'02_检测区/检测区合稿字段映射.json', fieldmap)
            except Exception as ex:
                self.issue('error', 'SHP_EXPORT_FAILED', 'detector/merged', detail=str(ex))

    def write_styles(self):
        from style_builder import build_styles
        report = build_styles(self.cfg, self.base, self.out, self.stats)
        if report.get('unmapped_reference_sources'):
            self.issue('review', 'STYLE_REFERENCE_REBOUND', detail='Reference uses historical vector tile sources. Generated local GeoJSON styles use explicit semantic mappings; inspect visual appearance and target-engine compatibility.')

    def write_csv(self):
        p = self.out/'审核/issues.csv'
        with p.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['severity', 'code', 'layer', 'source', 'row', 'detail'], extrasaction='ignore')
            w.writeheader()
            for issue in self.issues:
                # Neutralize spreadsheet formulas while retaining JSON as the exact issue record.
                row = {k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v) for k, v in issue.items()}
                w.writerow(row)

    def write_report(self, audit):
        from report_builder import write_report
        write_report(self.out, audit, self.groups, self.geoms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    Pipeline(args.manifest, args.output).run()


if __name__ == '__main__':
    main()
