# 高精地图审核与合稿

审核选定批次的路口高精地图和检测区，整理 GeoJSON、SHP、配套样式及可回溯的问题记录；支持按已验证样例生成 MineData 分层导入包。

技能入口：[SKILL.md](SKILL.md)。

## 使用流程

1. 按 [审核规则](references/rules.md) 明确来源、版本、坐标基准与审核范围。
2. 按 [流水线说明](references/pipeline.md) 编写输入清单，运行 `scripts/hdmap_pipeline.py`，读取审核结论和问题清单。
3. 需要 MineData 导入时，按 [导入适配说明](references/minedata-import.md) 运行 `scripts/minedata_package.py`，生成并核验每层一个 ZIP 的六件套。

Python 依赖见 [requirements.txt](scripts/requirements.txt)，在项目环境中安装。输入和输出路径由本批清单指定；脚本保留原件并要求使用新输出目录。项目参考路径集中在 [张家口来源说明](references/zhangjiakou-context.md)，在其他环境使用时替换为实际资料位置。

本地包结构检查、平台导入结果、地图质量验收分别记录。`BLOCKED` 或 `REVIEW_REQUIRED` 表示仍有待处理事项。

## 测试

在项目过程目录创建测试工作区，然后使用已安装依赖的 Python 运行：

```sh
HDMAP_TEST_WORKSPACE="<项目过程目录>/pipeline-tests" python scripts/test_pipeline.py
HDMAP_TEST_DIR="<已创建的项目过程目录>/packaging-tests" python scripts/test_minedata_package.py -v
```

测试覆盖数量守恒、坐标转换、字段与几何保留、MineData 打包和异常输入处理。MineData 脚本不会执行平台上传。
