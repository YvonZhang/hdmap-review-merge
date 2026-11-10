# MineData SHP 导入适配

## 使用范围和证据

用于选定 SHP 成果的打包和导入问题定位。成功样例来自用户 2026-11-10 提供的 `MineData_SHP图层导入处理记录.md` 与 `SHP_ZIP_MineData_136`，原路径在 `/Users/yvonzhang/Downloads/`；项目归档见 [zhangjiakou-context.md](zhangjiakou-context.md)。现场成功由用户记录，本技能更新做了本地校验，未再次上传。

该实例同时调整了目录、文件名和坐标系配套文件，不能单独证明 QPJ、目录或压缩方法是失败根因。跨项目或平台实例时先取当前模板或已成功样例；下面的 `minedata_20261110_wgs84` 是可复现的已知组合，不是 MineData 所有版本的统一规范。

## 先诊断输入

1. 明确本批范围、选定版本和命名前缀。外层总包只作为运输容器：检查内层 ZIP、SHP 及伴随文件，忽略 `__MACOSX`、`._*` 和 `.DS_Store`；不要把所有历史候选自动合入。
2. 以 SHP 文件头与记录确定几何类型，核对 SHX 偏移、SHP/DBF 数量、PRJ、CPG、字段及几何有效性。文件名含 `line` 不代表线几何；本例人行横道、停止线、白黄标线都是面。
3. 原则上保留原字段。原 `AuditUid` 和 `FID` 的线层已试传成功；模板的 `name`、`Adresss`、`Tel`（均 C254，其中 `Adresss` 为模板原拼写）只用于独立诊断副本，不是业务字段规范。
4. 核实坐标来源及转换记录。仅在原坐标已是 WGS84 地理经纬度、PRJ 等价时套用样例 PRJ/QPJ。经纬度范围和文件夹“84”不能证明基准；GCJ02、BD09、未知基准、投影坐标需先解决，不得改标签充当转换。

## 成功实例的包结构

每层单独一个 ZIP，ZIP、一级目录、六个伴随文件使用同一基名。按用户命名约定，例如 `136_20261110_2_cross_border_ln`；`136` 是前缀，覆盖路口数另核。

```text
136_20261110_2_cross_border_ln.zip
└── 136_20261110_2_cross_border_ln/
    ├── 136_20261110_2_cross_border_ln.cpg
    ├── 136_20261110_2_cross_border_ln.dbf
    ├── 136_20261110_2_cross_border_ln.prj
    ├── 136_20261110_2_cross_border_ln.qpj
    ├── 136_20261110_2_cross_border_ln.shp
    └── 136_20261110_2_cross_border_ln.shx
```

- SHP、SHX、DBF、CPG 从选定输入逐字节保留；不修形、不改字段、不转码。
- PRJ 采用已核验成功样例的 WGS84 WKT；QPJ 采用其 EPSG:4326 WKT。此操作不变更坐标。
- 本例目录条目与 CPG 为 `ZIP_STORED`，其余五件套为 `ZIP_DEFLATED`。用此配置复现，不据此推断其他压缩形式一定失败。
- 先检查所有输出名冲突，再写入新目录。提交目录仅放选定最终 ZIP，试验版、模板字段版和扁平结构版放在过程目录。

## 脚本运行

依赖复用 `scripts/requirements.txt`。对于 GeoJSON 先运行通用审核流水线导出 SHP，再进入本步骤；已有 SHP 直接打包。本脚本支持显式选择的单层 ZIP、带 `member` 的多层 ZIP、或同名伴随文件完整的 `.shp`。外层 ZIP 内仍是内层 ZIP 时，先在项目过程目录安全展开选定内层包，再填写清单；脚本不会递归挑版本。

清单示例（路径相对于清单目录；证据文字应填写实际核验结果）：

```json
{
  "profile": "minedata_20261110_wgs84",
  "scope_note": "填写实际路口和图层范围，前缀不作为覆盖数量依据",
  "coordinate_basis": "wgs84",
  "basis_evidence": "填写原坐标声明、转换记录及PRJ等价核验依据",
  "reference_zip": "../依据/已成功的图层.zip",
  "reference_evidence": "填写模板来源或试传成功记录",
  "output_prefix": "136_20261110",
  "inputs": [
    {"path": "../审核成果/01_高精地图/SHP_ZIP/batch_2_cross_border_ln.zip", "layer": "2_cross_border_ln"},
    {"path": "../审核成果/01_高精地图/SHP_ZIP/batch_12_crosswalk_line_pl.zip", "layer": "12_crosswalk_line_pl"}
  ]
}
```

```sh
"<项目环境>/bin/python" "<skill>/scripts/minedata_package.py" pack \
  --manifest "<项目>/过程/MineData清单.json" \
  --output "<项目>/MineData提交_新版本"

"<项目环境>/bin/python" "<skill>/scripts/minedata_package.py" inspect \
  "<项目>/MineData提交_新版本/SHP_ZIP/"*.zip \
  --report "<项目>/过程/提交包复核.json"
```

`pack` 先检查所有输入，再创建新输出目录。该配置限定 WGS84、UTF-8、二维 PolyLine(3)/Polygon(5)；Z/M、空几何、无效几何、删除的 DBF 记录、未知或非 WGS84 PRJ、QPJ 冲突、几何类型与 `_ln/_pl` 名称不符均停止，交上游明确处理，不静默修复。

产物：`SHP_ZIP/`、`manifest.used.json`、`packaging_audit.json`。审计记录包含来源和哈希、数量、DBF 字段、实际线/面类型、CRS、样例来源及保留字节对照。逐包重读 CRC、目录、六件套名称和压缩方式；重核 SHX 索引、DBF 数量、几何和坐标范围。`inspect` 可单独检查用户交来的最终包，不重写数据；其布局检查仅针对本配置。

脚本状态区分 `local_package_check=PASSED`、`platform_import=NOT_TESTED_BY_SCRIPT`、`map_acceptance=NOT_ASSESSED`。导入结果和地图质量审核另记，不自动改原 `audit.json`。

## 平台试传和失败定位

只有用户请求包含平台操作时才上传。已获授权的同类导入可先用一个较小图层验证，再按结果批量处理。记录中的入口为“资产管理 → 我的数据 → 数据仓库”，实际页面以当前实例为准；按实际 SHP 类型选“线数据”或“面数据”，每次选一个图层 ZIP，数据集名称与包基名一致。完成后核对名称、线/面标识、要素数及地图展示；批量命名后如仅做本地检查，不能写成每个新名字已重新上传成功。

`POST /service/upload/file` 返回 HTTP 200，但业务体 `errcode=-1`、`errmsg=数据上传失败，请参照上传数据说明`，仍是业务失败。保存时间、接口、数据集名、请求标识和业务响应；这一通用错误不能定位唯一原因。有授权时先用平台自身模板在相同入口试传；模板也失败则按时间和请求标识查询服务日志。不要无限变换字段或盲目修改坐标系。

本例将五件套扁平放到 ZIP 根目录仍失败；保留 `AuditUid/FID` 并匹配模板目录和 PRJ/QPJ 后线层成功，随后九个面层同方式整理。保留模板字段的试验副本不进入最终提交目录。

## 2026-11-10 样例清单

以下文件名前缀均为 `136_20261110_`。最终目录只有高精地图图层；不含检测区、样式。

| 图层后缀（含 ZIP 扩展名） | 上传类型 | 要素数 |
| --- | --- | ---: |
| `1_cross_outline_pl.zip` | 面数据 | 2 |
| `2_cross_border_ln.zip` | 线数据 | 44 |
| `6_laneline_W_pl.zip` | 面数据 | 17 |
| `7_laneline_Y_pl.zip` | 面数据 | 56 |
| `9_lane_stop_line_pl.zip` | 面数据 | 7 |
| `12_crosswalk_line_pl.zip` | 面数据 | 101 |
| `28_manhole_cover_pl.zip` | 面数据 | 45 |
| `33_lane_arrow_pl.zip` | 面数据 | 10 |
| `35_bridge_pier_pl.zip` | 面数据 | 8 |
| `36_bridge_culvert_pl.zip` | 面数据 | 2 |

合计 10 层，线 44、面 248，共 292。10 层均为 `AuditUid C24`、`FID N18(0)`，这是本批字段事实，不是以后数据必须服从的模板。前期源数据含 Z/M 的保留和二维转换属于上游过程；这里的成功包是二维，不能据此宣称保留了原始三维信息。
