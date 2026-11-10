# 脚本输入与交付契约

## 运行

在目标项目内使用已有 Python 环境，缺依赖才建 venv 并按 `scripts/requirements.txt` 安装。入口：

```sh
"<项目环境>/bin/python" "<skill>/scripts/hdmap_pipeline.py" \
  --manifest "<项目>/配置/manifest.json" \
  --output "<项目>/成果_新版本"
```

输出目录已存在时停止，改用新版本目录。不要为了重跑删除用户原件。脚本成功退出表示审核产物生成成功，是否有阻断项必须读取 audit.json 的状态；它不会给出未经人工验收的 PASS。

## 输入清单

```json
{
  "profile": "spec20241118",
  "scope_note": "明确本批实际范围，区分参考样本与正式全量",
  "coordinate_basis": "wgs84",
  "basis_evidence": "供应商坐标声明、PRJ及控制点核验的实际证据",
  "output_prefix": "batch01",
  "deduplicate_exact": true,
  "expected_bbox": [114.6, 40.5, 115.1, 41.1],
  "expected_layers": ["1_cross_outline_pl"],
  "style_reference": "../输入/参考样式.json",
  "inputs": [
    {"role": "hdmap", "layer": "1_cross_outline_pl", "path": "../输入/路口A/1_cross_outline_pl.zip"},
    {"role": "hdmap", "layer": "1_cross_outline_pl", "path": "../输入/路口B/1_cross_outline_pl.geojson"},
    {"role": "detector", "layer": "detector_13070200012", "path": "../输入/检测区.shp", "intersection_id": "13070200012", "field_map": {"LaneEventD": "LaneEventDetectorCategoryId"}}
  ]
}
```

示例的路径和路口 ID 应替换为本批真实值；`layer`、`output_prefix` 只允许英文字母、数字、下划线和连字符。高精地图的 layer 使用 `assets/layer_catalog.json` 的规范名称，例如 `6_laneline_W_ln`，同一名称自动合并多个选定来源。新规范面版使用 `_pl`，不得把旧线文件映射成该名。

所有相对路径相对于 manifest 所在目录。`profile` 目前支持 `spec20241118`（检查七类线改面差异）和 `legacy2023`（历史结构整理，仍不代表验收通过）。`coordinate_basis=wgs84` 要有明确依据，不由经纬度范围自动推定。`expected_bbox` 是项目范围，不是固定张家口以外任务的默认值。

ZIP 默认必须恰有一个 SHP；多图层 ZIP 以每个输入对象的 `member` 选择具体条目。同名 `.shp/.shx/.dbf` 必需，`.prj/.cpg` 缺失时分别用有依据的 `crs_override`、`encoding` 显式声明；不要默认添加 UTF-8。所有标准投影转换通过 pyproj 且经度在前；GCJ02/BD09 或坐标来源未知需要独立解决，不在本脚本自动转换。

SHP 支持二维 Point/Polyline/Polygon 文件读取，本工作流输出按道路线/面与检测区面校验；含 Z/M、GeometryCollection 等输入直接报出，不默默降维。GeoJSON 支持 FeatureCollection。非标准 NaN/Infinity 拒绝读取。

检测区字段映射需按实测配置，不自动按模糊名称猜。规范类别为字符串 1–4，LaneId 保持三位字符串。缺官方路口 ID 时生成 `local:<数据集名>` 只隔离本地审核范围，不宣称其为平台编号。人工可用补充资料后替换，重新运行。

## 输出

```text
成果目录/
  01_高精地图/GeoJSON/      每个语义图层一个合稿
  01_高精地图/SHP_ZIP/      一层一包；包内同名文件夹和五件套
  01_高精地图/字段映射/
  02_检测区/GeoJSON/        按选定路口或独立数据集
  02_检测区/SHP_ZIP/
  02_检测区/检测区合稿.geojson
  02_检测区/检测区合稿.zip
  03_样式/                 原始样式、三个本地样式、绑定映射
  审核/                    HTML、JSON、CSV、逐要素去向、隔离数据、真实图示
  manifest.used.json
  checksums.sha256.json
```

每个 SHP ZIP 均包含 `.shp/.shx/.dbf/.prj/.cpg`；GeoJSON 作为完整字段和属性类型的权威副本。DBF 字段限长使用显式短名表；浮点属性写为精确十进制文本，避免 DBF 固定精度舍入。嵌套属性写为 JSON 文本。超过 254 UTF-8 字节不截断，报导出阻断。DBF 无法无损区分字符串 null/空串、保留首尾空格，相关字段的原始语义回到 GeoJSON，不用 SHP 重建唯一原件。

这是通用审核导出结构。面向 MineData 数据仓库时，继续按 [minedata-import.md](minedata-import.md) 使用 `minedata_package.py` 生成专用六件套并核验；已有成果仅调整打包时直接进入该步骤。此步骤逐字节保留选定 SHP/SHX/DBF/CPG，不重复转换和导出，不改变原审核状态。

`AuditUid` 关联 GeoJSON Feature.id 及 provenance；原始业务 id 保留。完全重复的判据为同层、规范化几何坐标完全相同且全部业务属性相同；零容差，不把仅形状相近的对象当重复。开启去重后记录保留 UID 与删除来源行。无效几何和非法检测区属性在 `审核/隔离` 保存原始要素。业务键冲突要素保留供复核，同时标阻断；合稿不能直接投产。

数量守恒必须满足：已成功读取输入数 = 输出数 + 完全去重数 + 隔离数。无法读取的文件另列 INPUT_READ_FAILED，不计为已读取要素，也不能被零错误统计掩盖。

## 验证重点

每个产物由脚本读回：SHP 数量、几何坐标和属性；GeoJSON 数量；全部样式本地引用；同名字段冲突；数量守恒。脚本测试还应覆盖中文编码、字段截断别名、不同路口同 LaneId、重复与属性冲突、空几何/自交、投影坐标、重复输出目录和损坏输入。

本地样式引用路径相对于样式 URL/文件目录。实际页面使用时由宿主解析相对路径或经本地 HTTP 提供整个成果目录，不能只拷贝样式 JSON。原始样式含外部瓦片/sprite/glyph 资源，离线成果不能证明这些服务当前可访问。
