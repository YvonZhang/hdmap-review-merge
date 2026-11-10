"""Generate portable local GeoJSON styles with an explicit historical-style mapping."""
import hashlib
import json
import shutil
from pathlib import Path


def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def build_styles(cfg, base, out, stats):
    root = out/'03_样式'
    root.mkdir(exist_ok=True)
    catalog = json.loads((Path(__file__).resolve().parents[1]/'assets/layer_catalog.json').read_text())
    ref, refhash = {}, None
    if cfg.get('style_reference'):
        path = (base/cfg['style_reference']).resolve()
        raw = path.read_bytes()
        refhash = hashlib.sha256(raw).hexdigest()
        ref = json.loads(raw)
        shutil.copy2(path, root/'原始参考样式.json')
    hd = {'version': 8, 'name': '高精地图 本地数据适配样式', 'sources': {}, 'layers': [],
          'metadata': {'status': 'review', 'source_path_base': 'style JSON directory; use HTTP serving or resolve paths in host',
                       'reference_sha256': refhash, 'render_width': 'display pixels, not measured road-marking width'}}
    detector = {'version': 8, 'name': '检测区 本地数据适配样式', 'sources': {}, 'layers': []}
    mappings = []
    ordered = sorted([(g, s) for g, s in stats.items() if s['role'] == 'hdmap' and s['output']], key=lambda x: catalog.get(x[1]['layer'], {}).get('z', 50))
    for group, s in ordered:
        layer = s['layer']
        c = catalog.get(layer, {})
        source_id = layer
        hd['sources'][source_id] = {'type': 'geojson', 'data': '../'+s['files']['geojson']}
        is_polygon = layer.endswith('_pl')
        color = c.get('color', '#f4f5f6')
        typ = 'fill' if is_polygon else 'line'
        paint = {'fill-color': color, 'fill-opacity': 1} if is_polygon else {
            'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 0.3, 16, 1, 20, 3]}
        layout = {'visibility': 'visible'}
        if not is_polygon:
            layout.update({'line-cap': 'round', 'line-join': 'round'})
        hd['layers'].append({'id': source_id, 'source': source_id, 'type': typ, 'layout': layout, 'paint': paint})
        historic = [l for l in ref.get('layers', []) if l.get('source') == c.get('reference_source')]
        mappings.append({'output_layer': layer, 'display_name': c.get('name', layer), 'reference_source': c.get('reference_source'),
                         'reference_layer_ids': [l['id'] for l in historic], 'reference_visibility': [l.get('layout', {}).get('visibility', 'visible') for l in historic],
                         'new_source': hd['sources'][source_id], 'new_type': typ, 'new_color': color,
                         'method': 'Semantic mapping; display colors/visibility adapted for inspection, no claim of pixel-identical reproduction'})
    if (out/'02_检测区/检测区合稿.geojson').exists():
        detector['sources']['detectors'] = {'type': 'geojson', 'data': '../02_检测区/检测区合稿.geojson'}
        for cat, name, color in [('1', '到达', '#24c6dc'), ('2', '进入', '#46d17e'), ('3', '通过', '#ffad42'), ('4', '驶离', '#cc83ff')]:
            detector['layers'].append({'id': 'detector_'+cat, 'source': 'detectors', 'type': 'fill',
                'filter': ['==', ['get', 'LaneEventDetectorCategoryId'], cat],
                'paint': {'fill-color': color, 'fill-opacity': 0.6, 'fill-outline-color': color},
                'metadata': {'category': name}})
    combined = {'version': 8, 'name': '高精地图与检测区 审核叠加',
                'sources': {**hd['sources'], **detector['sources']},
                'layers': [{'id': 'background', 'type': 'background', 'paint': {'background-color': '#17232d'}}, *hd['layers'], *detector['layers']],
                'metadata': hd['metadata']}
    for name, style in [('高精地图.local.style.json', hd), ('检测区.local.style.json', detector), ('合稿.local.style.json', combined)]:
        ids = [l['id'] for l in style['layers']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate style layer IDs')
        for layer in style['layers']:
            if layer.get('source') and layer['source'] not in style['sources']:
                raise ValueError('Unbound style source')
            if 'source-layer' in layer:
                raise ValueError('GeoJSON style must not carry vector-tile source-layer')
        for source in style['sources'].values():
            if not (root/source['data']).resolve().is_file():
                raise ValueError('Style data file is missing')
        write(root/name, style)
    report = {'reference_sha256': refhash, 'reference_sources': len(ref.get('sources', {})), 'reference_layers': len(ref.get('layers', [])),
              'unmapped_reference_sources': sorted(set(ref.get('sources', {})) - {m['output_layer'] for m in mappings}),
              'mapping': mappings, 'validation': 'JSON structure and all local references verified; target MineMap engine rendering not executed',
              'deployment_note': 'Original style includes hosted vector/sprite/glyph dependencies. Adapted styles are local GeoJSON, omit those dependencies and MineMap-only layout keys. Serve package over HTTP or let host resolve paths relative to style URL.'}
    write(root/'样式映射与验证.json', report)
    return report
