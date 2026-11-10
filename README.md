# 高精地图审核与合稿

`hdmap-review-merge` 是一个处理路口高精地图和检测区的 Codex skill。给它选定批次的 GeoJSON、SHP 或图层 ZIP，可以完成数据审核、分层合稿、样式整理，以及 MineData 导入包生成。

主要输出：

- **高精地图与检测区**：分层 GeoJSON、SHP ZIP、字段映射和逐要素来源。
- **配套样式**：高精地图、检测区及两者叠加的本地 GeoJSON 样式。
- **审核记录**：HTML 报告、问题清单、隔离数据和文件校验值。
- **MineData 导入包**：按已验证样例，一层一个 ZIP，包含同名目录与六件套。

[安装](#安装) · [在 Codex 中使用](#在-codex-中使用) · [运行示例](#运行示例) · [生成 MineData 导入包](#生成-minedata-导入包) · [常见问题](#常见问题)

## 安装

准备 Git、Python 3.12 或更新版本，以及可使用本地 skill 的 Codex。脚本也可以独立运行。

### macOS、Linux 或 WSL

在终端执行：

```bash
HDMAP_SKILL="$HOME/.agents/skills/hdmap-review-merge"
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/YvonZhang/hdmap-review-merge.git "$HDMAP_SKILL"

python3 -m venv "$HDMAP_SKILL/.venv"
"$HDMAP_SKILL/.venv/bin/python" -m pip install -r "$HDMAP_SKILL/scripts/requirements.txt"
"$HDMAP_SKILL/.venv/bin/python" "$HDMAP_SKILL/scripts/hdmap_pipeline.py" --help
```

### Windows PowerShell

```powershell
$hdmapSkill = Join-Path $env:USERPROFILE ".agents\skills\hdmap-review-merge"
New-Item -ItemType Directory -Force (Split-Path $hdmapSkill) | Out-Null
git clone https://github.com/YvonZhang/hdmap-review-merge.git $hdmapSkill

py -3 -m venv "$hdmapSkill\.venv"
& "$hdmapSkill\.venv\Scripts\python.exe" -m pip install -r "$hdmapSkill\scripts\requirements.txt"
$env:PYTHONUTF8 = "1"
& "$hdmapSkill\.venv\Scripts\python.exe" "$hdmapSkill\scripts\hdmap_pipeline.py" --help
```

`py -3` 应指向 Python 3.12 或更新版本。`PYTHONUTF8=1` 用于读取中文清单和报告；在新的 PowerShell 会话中运行脚本时也设置该变量。

Codex 从 `~/.agents/skills/` 发现用户技能，安装后通常会自动识别。CLI 或 IDE 扩展中可通过 `/skills` 查看，或输入 `$hdmap-review-merge` 调用；未显示时重启 Codex。目录和调用方式见 [OpenAI 官方技能文档](https://developers.openai.com/codex/skills/)。

已有同名安装时，沿用原目录。更新命令见文末的[更新与测试](#更新与测试)。

## 在 Codex 中使用

打开存放地图资料的项目，把路径、选定版本、坐标依据和输出位置写进请求。以下路径替换为自己的项目路径；已有 Python 环境时也一并提供。

### 审核并合稿

```text
使用 $hdmap-review-merge 审核并整理这批路口地图。

高精地图：/data/project/input/hdmap
检测区：/data/project/input/detectors
路口编码表：/data/project/input/cross.xlsx
样式参考：/data/project/input/style.json
坐标依据：供应方说明为 WGS84，请结合 PRJ 和坐标范围核对。
本批范围：路口 A、路口 B，采用各自 2026-11-10 版本。
输出目录：/data/project/output/review-v1
Python 环境：/data/project/.venv/bin/python

按 2024-11-18 规范审核，分别输出高精地图、检测区和样式，
附问题清单、数量核对和逐要素来源记录。
```

编码表由 agent 用来核对路口信息；命令行流水线通过清单中的 `intersection_id` 接收核定编码。

### 为已选定成果制作 MineData 包

```text
使用 $hdmap-review-merge 整理 MineData 导入包。

选定 SHP 成果：/data/project/review/01_高精地图/SHP_ZIP
当前实例已成功导入的样例：/data/project/reference/successful-layer.zip
坐标依据：选定成果已转换为 EPSG:4326，转换记录在 /data/project/reference/crs.json。
命名前缀：batch01_20261110
输出目录：/data/project/output/minedata-v1

参照成功样例打包，保留 SHP、SHX、DBF、CPG 的原始字节，
核对每层的线面类型、数量和六件套结构，并生成提交清单。
```

## 运行示例

仓库自带一个人工构造的示例路口：1 个道路轮廓、1 个边界线要素、4 个检测区，共 6 个要素。坐标使用 WGS84，用于熟悉输入清单和输出结构。

示例清单在 [examples/quickstart/manifest.json](examples/quickstart/manifest.json)。完成安装后运行：

**macOS、Linux 或 WSL：**

```bash
HDMAP_SKILL="$HOME/.agents/skills/hdmap-review-merge"
cd "$HDMAP_SKILL"
HDMAP_PY="$HDMAP_SKILL/.venv/bin/python"

"$HDMAP_PY" scripts/hdmap_pipeline.py \
  --manifest examples/quickstart/manifest.json \
  --output work/review
```

**Windows PowerShell：**

```powershell
$hdmapSkill = Join-Path $env:USERPROFILE ".agents\skills\hdmap-review-merge"
Set-Location $hdmapSkill
$env:PYTHONUTF8 = "1"
& ".\.venv\Scripts\python.exe" scripts/hdmap_pipeline.py `
  --manifest examples/quickstart/manifest.json `
  --output work/review
```

打开 `work/review/审核/审核报告.html` 查看结果。预期读取 6 个、输出 6 个、去重 0 个、隔离 0 个，状态为 `REVIEW_REQUIRED`：测绘精度、现场覆盖及检测区位置保留为人工复核项。

```text
work/review/
├── 01_高精地图/       GeoJSON、SHP_ZIP、字段映射
├── 02_检测区/         分层数据及检测区合稿
├── 03_样式/           三份本地样式与映射记录
├── 审核/              HTML 报告、audit.json、issues.csv、provenance.json
├── manifest.used.json
└── checksums.sha256.json
```

### 换成自己的数据

复制示例清单到项目中，修改这些字段：

| 字段 | 填写内容 |
| --- | --- |
| `inputs` | 逐项列出选定文件、`role` 和规范 `layer` 名称；相对路径以清单所在目录为起点 |
| `profile` | `spec20241118` 为 2024 规范；`legacy2023` 用于历史结构整理 |
| `coordinate_basis`、`basis_evidence` | 实际坐标基准及来源证据；WGS84 使用 `wgs84` |
| `expected_bbox` | 本项目的经纬度范围，顺序为西、南、东、北 |
| `expected_layers` | 本批明确要求交付的高精地图图层 |
| `output_prefix` | 输出文件前缀，只使用英文字母、数字、下划线和连字符 |
| `intersection_id` | 填在每个检测区输入对象中，使用核定路口编码；示例的 `demo_001` 是演示标识 |
| `style_reference` | 可选，参考样式 JSON 的路径 |

SHP 输入需配齐同名的 `.shp/.shx/.dbf/.prj/.cpg`。检测区保留 `LaneId` 和 `LaneEventDetectorCategoryId`；若 DBF 使用短字段名，在输入对象中填写 `field_map`。清单格式和投影转换说明见 [流水线契约](references/pipeline.md)。

每次运行使用一个新的输出目录，例如 `work/review-v2`。完整属性以 GeoJSON 为准，SHP 短字段名通过输出的字段映射对应。

## 生成 MineData 导入包

完成上面的示例后，把当前 MineData 实例的模板或已成功图层 ZIP 放到 `work/minedata-reference.zip`。样例需带 WGS84 的 PRJ、QPJ 和 UTF-8 编码声明；脚本会检查它的配套文件、实际几何和坐标系。

在 `work/minedata-manifest.json` 保存以下清单，并填写 `reference_evidence` 的真实来源。这个示例处理刚才生成的两个高精地图层：

```json
{
  "profile": "minedata_20261110_wgs84",
  "scope_note": "人工示例路口的道路轮廓和边界线，共2层、2个要素",
  "coordinate_basis": "wgs84",
  "basis_evidence": "来自仓库 quickstart 的人工 WGS84 经纬度示例",
  "reference_zip": "minedata-reference.zip",
  "reference_evidence": "填写当前实例模板或成功样例的来源、核验时间",
  "output_prefix": "demo_20261110",
  "inputs": [
    {"path": "review/01_高精地图/SHP_ZIP/demo_1_cross_outline_pl.zip", "layer": "1_cross_outline_pl"},
    {"path": "review/01_高精地图/SHP_ZIP/demo_2_cross_border_ln.zip", "layer": "2_cross_border_ln"}
  ]
}
```

以下命令使用 Bash，继续在仓库根目录执行：

```bash
"$HDMAP_PY" scripts/minedata_package.py pack \
  --manifest work/minedata-manifest.json \
  --output work/minedata

"$HDMAP_PY" scripts/minedata_package.py inspect \
  work/minedata/SHP_ZIP/*.zip \
  --report work/minedata-check.json
```

输出为 `work/minedata/SHP_ZIP/` 中的两个图层 ZIP，以及 `packaging_audit.json` 和使用的清单。每个 ZIP 包含同名目录与 `.shp/.shx/.dbf/.prj/.qpj/.cpg`；SHP、SHX、DBF、CPG 与输入逐字节一致。

该配置接受已明确为 WGS84 的二维线和面。平台上传时按实际 SHP 类型选择“线数据”或“面数据”；具体样例适配、压缩方式和错误定位见 [MineData 导入说明](references/minedata-import.md)。

## 如何判断结果

| 结果 | 含义与下一步 |
| --- | --- |
| `审核/audit.json`：`BLOCKED` | 有阻断问题，按 `issues.csv` 修正数据后重新运行 |
| `审核/audit.json`：`REVIEW_REQUIRED` | 自动检查已完成，继续核对测绘精度、覆盖、检测区位置及目标引擎样式 |
| `packaging_audit.json`：`local_package_check=PASSED` | 本地包结构及数据完整性检查通过，可进入平台导入验证 |

地图审核、平台导入和样式实机验证分别记录。流水线成功退出表示审核产物已生成，验收结论以问题清单和人工复核为准。

## 常见问题

| 情况 | 处理方法 |
| --- | --- |
| Codex 找不到技能 | 检查安装目录内是否直接包含 `SKILL.md`，然后重启 Codex |
| `ModuleNotFoundError` | 使用安装依赖的 `.venv` 中的 Python 运行脚本 |
| `Output already exists` | 换一个输出目录，保留原审核结果 |
| 坐标基准不明，或数据为 GCJ02/BD09 | 先核实坐标来源并完成转换，再填写清单 |
| SHP 含 Z/M 维度 | 先明确二维交付要求，另存原始数据并记录转换过程 |
| MineData 返回 HTTP 200，业务码却为 `errcode=-1` | 按业务失败排查；结合响应、上传时间及平台日志定位 |

## 更新与测试

macOS、Linux 或 WSL 在仓库目录执行。已有本地修改时，先处理修改再更新：

```bash
HDMAP_SKILL="$HOME/.agents/skills/hdmap-review-merge"
cd "$HDMAP_SKILL"
HDMAP_PY="$HDMAP_SKILL/.venv/bin/python"

git pull --ff-only
"$HDMAP_PY" -m pip install -r scripts/requirements.txt

mkdir -p work/tests/pipeline work/tests/packaging
HDMAP_TEST_WORKSPACE="$PWD/work/tests/pipeline" \
  "$HDMAP_PY" scripts/test_pipeline.py
HDMAP_TEST_DIR="$PWD/work/tests/packaging" \
  "$HDMAP_PY" scripts/test_minedata_package.py -v
```

当前两组测试共 19 项，覆盖数量守恒、坐标转换、中文字段、几何保留、打包和异常输入处理。

详细入口：[技能工作流](SKILL.md) · [审核规则](references/rules.md) · [图层目录](assets/layer_catalog.json) · [项目案例](references/zhangjiakou-context.md)。
