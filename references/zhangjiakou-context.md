# 张家口历史成果的来源和含义

## 来源

历史地图根目录：
`/Users/yvonzhang/Library/CloudStorage/OneDrive-智慧互通科技股份有限公司/22_AITS历史/01_SBG/地图`

本次过程与成果根目录：
`/Users/yvonzhang/Library/CloudStorage/OneDrive-智慧互通科技股份有限公司/11_AITS/项目资料/CN/张家口/04_审核与工具/高精地图审核整理_20261109`

两份用户指定规范原件位于：
`/Users/yvonzhang/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_0471534716712_3525/msg/file/2026-09/`

- `高精地图采集需求及详细要求及审核要求-20241118(1).docx`
- `路口检测区绘制说明文档V1.1(1).docx`

成果形式参考：`高精地图/张家口 ssw/122总稿/5_res_84`。
样式参考：`minemap地图样式/minedata_cn/minemap_style_3.0.0_18786.json`。

这是本次调查的历史定位，不是未来任务可以不验证的当前状态。后续用户指定其他版本时以新范围为准。

## 目录在做什么

从规范、目录产物、Notebook 和 QGIS 工程共同看，这套工作把路口测绘/描绘数据按交通设施语义分层，逐路口审核和修订，再按期合并，做坐标/格式适配并为地图展示引擎打包；检测区在这些道路图层基础上绑定车道事件。它同时包含静态展示数据和事件检测业务几何，不能仅凭“高精地图”名称断定具备自动驾驶可用的全套车道拓扑与定位能力。

证据链：

1. `张家口 ssw` 保存 P1 6、P2 21、P3 23/23+1、P4 35-1、p5 补足等分期目录和多次合稿。数字是目录标签，尚未逐个核验路口清单。
2. `122总稿` 中 `0_original` → `1_mapshapered` → `4_addcpg_temp_file_84` → `5_res_84`，体现原始合稿、Mapshaper 处理、补 CPG 和最终 ZIP。并有 `2_QGIS_84_to_02`、`3_mapshepered_02` 坐标转换支线；仅凭目录无法还原全部 Mapshaper 命令或证明精度无损。
3. `add_cpg_to_shapefile_zip.ipynb` 实际代码是解包、写 `UTF-8` CPG、重打包；没有执行 DBF 字符转码，不能将此历史脚本当作编码已验证的证据。
4. 根部 `高精地图.qgz` 的 26 个主图层实际指向 `122总稿/5_res_84` ZIP；还带 KML 补图和底图引用，其中部分旧路径可能失效。
5. 同级存在 `2023-11-01_136路口合稿`、`2023-11-09_136路口与路段合稿` 及“失败后重新打包”等目录。说明有后续范围扩展和上传适配尝试；本次用户明确选 122 形式参考，不将后续目录自动替代它。
6. `LayersName` 记有 26 个文件名和 CamelCase 服务层名对应，例如 `122_1_cross_outline_pl` → `122CrossOutlinePl`，包括 `122bRoadPrintWPl/YPl` 的补充面层。
7. `检测区` 保存多路口 GeoJSON/SHP、编号表、SQLite 中间文件、修订副本和“7个路口识别区”集合；其中含重复和多种历史字段编码。

## 参考样式

实读指定样式：version 8、41 个 vector 源、186 个渲染层；源名属于 0719/0721/Merge_2 系列，没有 122 系列直接绑定。一些高精图层 visibility 为 none，还含 MineMap 专用 layout 属性及远程资源。

因此，保留该文件作为历史样式参考，按语义建立新数据绑定；不能仅把文件放进包就声称配套可用。自动生成样式保留部分配色线索，调整道路线/面和检测区可见性，附完整映射，目标引擎仍需实际渲染验证。

## 本次实测已证实的风险

26 个参考层中存在完全重复要素、空几何、自交/无效面和大量空值/零属性。立交涵洞层 PRJ 为 WGS84 基准的自定义横轴墨卡托米制投影，其余多数为 EPSG:4326；`84` 文件夹名不能证明所有文件都是经纬度。准确数量以项目最新审核报告为准。

## 2026-11-10 MineData 提交样例

用户提供 `Downloads/MineData_SHP图层导入处理记录.md` 和 `Downloads/SHP_ZIP_MineData_136` 作为最终可提交版本。项目归档位置为：
`/Users/yvonzhang/Library/CloudStorage/OneDrive-智慧互通科技股份有限公司/11_AITS/项目资料/CN/张家口/01_成品/03_MineData导入包/`

本批为两个路口的 10 个高精地图图层、292 个要素；包名前缀 `136` 不表示本批有 136 个路口。用户记录现场导入成功；本地复核确认 10 包结构、CRC、PRJ/QPJ、几何与数量通过，SHP/SHX/DBF/CPG 与前期二维导出逐字节一致。详细适配规则及数量表见 [minedata-import.md](minedata-import.md)。本样例不包含检测区和样式，也不改变既有审核包的质量结论。
