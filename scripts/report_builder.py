"""Self-contained audit report with real-data SVG views; no basemap or network calls."""
import collections
import html
import hashlib
import json
import math
from pathlib import Path
from shapely.geometry import box


def esc(v):
    return html.escape(str(v))


def svg_scene(groups, geoms, catalog, bbox, width=1000, height=720):
    west, south, east, north = bbox
    scale_x = math.cos(math.radians((north+south)/2))
    spanx, spany = (east-west)*scale_x, north-south
    scale = min((width-40)/spanx, (height-40)/spany)
    dx, dy = (width-spanx*scale)/2, (height-spany*scale)/2
    region = box(*bbox)
    def pos(pt):
        return ((pt[0]-west)*scale_x*scale+dx, (north-pt[1])*scale+dy)
    def coords(seq):
        return ' '.join(f'{x:.2f},{y:.2f}' for x,y in map(pos,seq))
    clip_id = 'clip_' + hashlib.sha256(str(bbox).encode()).hexdigest()[:12]
    pieces = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="高精地图与检测区实测叠加" style="overflow:hidden;background:#17232d"><defs><clipPath id="{clip_id}"><rect width="{width}" height="{height}"/></clipPath></defs><g clip-path="url(#{clip_id})"><rect width="100%" height="100%" fill="#17232d"/>']
    ordered = sorted(groups, key=lambda g: 200 if g.startswith('detector/') else catalog.get(g.split('/')[-1], {}).get('z',50))
    for group in ordered:
        name = group.split('/')[-1]
        for f in groups[group]:
            geom = geoms[f['id']]
            if not geom.intersects(region):
                continue
            c = catalog.get(name, {}).get('color', '#eee')
            detector = group.startswith('detector/')
            if detector:
                c = {'1':'#24c6dc','2':'#46d17e','3':'#ffad42','4':'#cc83ff'}.get(f['properties'].get('LaneEventDetectorCategoryId'),'#ff0000')
            parts = list(geom.geoms) if geom.geom_type.startswith('Multi') else [geom]
            for g in parts:
                if g.geom_type == 'Polygon':
                    rings = [g.exterior, *g.interiors]
                    path = ' '.join('M'+' L'.join(f'{x:.2f},{y:.2f}' for x,y in map(pos,r.coords))+' Z' for r in rings)
                    pieces.append(f'<path d="{path}" fill="{c}" fill-opacity="{0.65 if detector else 1}" fill-rule="evenodd" stroke="{c}" stroke-width="{0.7 if detector else 0}"/>')
                elif g.geom_type == 'LineString':
                    pieces.append(f'<polyline points="{coords(g.coords)}" fill="none" stroke="{c}" stroke-width="0.8"/>')
            if detector:
                x,y = pos(geom.representative_point().coords[0])
                pieces.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="#fff" font-size="7" text-anchor="middle">{esc(f["properties"].get("LaneId",""))}</text>')
    pieces.append('<text x="18" y="28" fill="white" font-size="14">N ↑ · WGS84 · 无底图</text></g></svg>')
    return ''.join(pieces)


def write_report(out, audit, groups, geoms):
    catalog = json.loads((Path(__file__).resolve().parents[1]/'assets/layer_catalog.json').read_text())
    t = audit['totals']
    layer_rows = ''.join(f'<tr><td>{esc(g)}</td><td>{s["input"]:,}</td><td>{s["output"]:,}</td><td>{s["deduplicated"]:,}</td><td>{s["quarantined"]:,}</td><td>{esc(s["geometry_types"])}</td></tr>' for g,s in audit['layers'].items())
    counts = collections.Counter(i['code'] for i in audit['issues'])
    code_rows = ''.join(f'<tr><td>{esc(k)}</td><td>{v}</td></tr>' for k,v in counts.most_common())
    source_rows = ''.join(f'<tr><td>{s["source_id"]}</td><td>{esc(s["path"])}</td><td>{s.get("input_features","读取失败")}</td></tr>' for s in audit['sources'])
    issue_rows = ''.join(f'<tr><td>{esc(i["severity"])}</td><td>{esc(i["code"])}</td><td>{esc(i["layer"])}</td><td>{esc(i["source"])}:{esc(i["row"])}</td><td>{esc(i["detail"])}</td></tr>' for i in audit['issues'])
    candidates = [(g,fs) for g,fs in groups.items() if g.startswith('detector/') and fs]
    scenes=[]
    # Deterministic spread of three source datasets for spatial inspection.
    picked = [candidates[i] for i in sorted({0,len(candidates)//2,len(candidates)-1})] if candidates else []
    for group,fs in picked:
        bounds = [geoms[f['id']].bounds for f in fs]
        bbox = [min(b[0] for b in bounds)-0.0005, min(b[1] for b in bounds)-0.0004,
                max(b[2] for b in bounds)+0.0005, max(b[3] for b in bounds)+0.0004]
        svg = svg_scene(groups,geoms,catalog,bbox)
        dest = out/'审核/图示'/f'{group.split("/")[-1]}.svg';dest.parent.mkdir(exist_ok=True);dest.write_text(svg)
        scenes.append(f'<figure><figcaption>{esc(group)} · 实际数据叠加，仅用于形状及相对位置检查</figcaption>{svg}</figure>')
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>高精地图与检测区审核结果</title>
<style>body{{font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#1b2937;background:#f4f6f8;margin:0}}main{{max-width:1180px;margin:auto;padding:40px 28px}}h1{{font-size:32px}}h2{{margin-top:44px}}p{{max-width:1000px}}.status{{font-size:20px;color:#a42b2b}}.stats{{display:flex;flex-wrap:wrap;gap:30px;padding:20px 0}}.stats strong{{display:block;font-size:30px}}table{{border-collapse:collapse;background:white;width:100%;font-size:13px}}th,td{{border:1px solid #dce1e7;padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#e8edf3}}.scroll{{overflow:auto;max-height:640px}}a{{color:#1560a8}}figure{{margin:28px 0}}svg{{display:block;width:100%;max-height:760px}}input{{padding:10px;width:96%;margin-bottom:10px}}details{{margin:25px 0}}.legend span{{display:inline-block;margin-right:20px}}</style><main>
<h1>高精地图与检测区审核结果</h1><p class="status">{audit['status']} · 审核整理包，尚未达到正式验收条件</p>
<p>{esc(audit.get('input_scope') or '按显式输入清单进行检查与合稿。')}</p>
<div class="stats"><div><strong>{t['input']:,}</strong>输入要素</div><div><strong>{t['output']:,}</strong>合稿保留</div><div><strong>{t['deduplicated']:,}</strong>完全重复去除</div><div><strong>{t['quarantined']:,}</strong>隔离待修复</div></div>
<p>数量守恒：输入 = 合稿保留 + 完全重复去除 + 隔离。完全重复按同层的规范化几何坐标与全部业务属性一致判断，不采用距离吸附、简化或自动修面。所有输入均保留在来源位置；处理去向详见 <a href="provenance.json">逐要素来源记录</a>。</p>
<p>2024 年规范中七类标线由线改面；旧线数据作为历史版本整理，不以改名或任意缓冲充当新规范成果。检测区编号按路口 + LaneId + 事件类别区分。测绘精度、250 m 覆盖、真实车道以及 EOC 对应仍需资料和现场依据核验。</p>
<p><a href="audit.json">完整机器报告</a> · <a href="issues.csv">问题清单 CSV</a> · <a href="../03_样式/样式映射与验证.json">样式映射</a> · <a href="../manifest.used.json">本次输入选择</a></p>
<h2>分层合稿统计</h2><div class="scroll"><table><thead><tr><th>图层</th><th>输入</th><th>保留</th><th>去重</th><th>隔离</th><th>实际几何</th></tr></thead><tbody>{layer_rows}</tbody></table></div>
<h2>问题分布</h2><table><tr><th>规则代码</th><th>条数</th></tr>{code_rows}</table>
<h2>实际数据图示</h2><p class="legend"><span style="color:#149bb0">■ 到达 1</span><span style="color:#23934b">■ 进入 2</span><span style="color:#c47413">■ 通过 3</span><span style="color:#8542ae">■ 驶离 4</span></p><p>图示没有外部底图；反映所选历史数据之间的相对位置，不能证明现状准确性或绝对测量精度。线条宽度是屏幕显示宽度。</p>{''.join(scenes)}
<h2>逐项问题</h2><input id="filter" placeholder="输入规则代码、图层或来源编号筛选"><div class="scroll"><table id="issues"><thead><tr><th>级别</th><th>代码</th><th>图层</th><th>源:行</th><th>说明</th></tr></thead><tbody>{issue_rows}</tbody></table></div>
<details><summary>输入来源及记录数</summary><table><tr><th>源编号</th><th>路径</th><th>数量</th></tr>{source_rows}</table></details>
<p>error 表示正式交付阻断项，review 表示需人工判定的事项，info 记录可复现的转换。报告完成与数据验收通过是两件事。</p>
<script>document.getElementById('filter').addEventListener('input',e=>{{let q=e.target.value.toLowerCase();document.querySelectorAll('#issues tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))}})</script></main></html>'''
    (out/'审核/审核报告.html').write_text(body,encoding='utf-8')
