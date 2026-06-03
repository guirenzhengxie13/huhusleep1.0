# 睡眠监测数据处理项目

本项目用于处理平台导出的睡眠监测 CSV 数据，按院区和日期自动归档，并生成睡眠事件、离床片段、告警数据、图表和 Excel 报表。

当前仓库是重构准备版本，目标是逐步减少对旧 Excel/TXT 依赖，同时保持输出结果和旧基线结构一致。

## 主要流程

- 睡眠主流水线：处理睡眠报告、呼吸心率、后台告警、离床图表和 Excel 报表。
- 测试跟踪独立流程：处理测试情况跟踪表和 `2.d.43` 数据。
- 失能周报独立流程：位于 `disability_weekreport/`，不接入睡眠主流水线。

## 流程边界

- `main.py` 只负责睡眠主流水线。
- `pipeline/test_tracker.py` 是测试跟踪独立流程，不由 `main.py` 调用。
- `disability_weekreport/main.py` 是失能周报独立流程，不由 `main.py` 调用。
- 三条流程共享 `assets/full_device_roster.csv` 作为设备主数据，但运行入口和输出目录保持独立。

## 目录约定

重构期主输出统一写入：

```text
C:\Users\Lenovo\Desktop\data
```

旧结果对照基线保留在：

```text
C:\Users\Lenovo\Desktop\data
```

平台导出的 CSV 默认从这里读取：

```text
C:\Users\Lenovo\Downloads
```

## 环境准备

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

如果需要运行失能周报流程，还需要确保本机已安装 `pandas` 和 `numpy`。

准备 ChromeDriver：

```bash
python tool/update_chromedriver.py
```

脚本会识别本机 Chrome 版本，并下载匹配的 `assets/chromedriver.exe`。该文件只保存在本地，不提交到 Git。

## 本地私有文件

公开仓库不提交账号、驱动、运行状态和输出结果。首次运行前，如需后台告警爬取，请在本地创建：

```text
assets/crawler_accounts.json
```

格式示例：

```json
{
  "default": {
    "username": "账号",
    "password": "密码"
  },
  "hk": {
    "username": "香港账号",
    "password": "密码"
  }
}
```

以下内容仅保留在本地：

- `assets/crawler_accounts.json`：后台告警爬虫账号。
- `assets/chromedriver.exe`：本机 ChromeDriver。
- `assets/pipeline_status.csv`：流水线断点状态表。
- `assets/旧依赖/`、`最新设备下载/`：旧表格依赖和平台导出备份。
- `data/`、`data/`：运行输出和对照基线。

## 统一设备总表

全项目设备基础信息统一来自：

```text
assets/full_device_roster.csv
```

当前必需字段：

```text
院区,设备号,老人姓名,房间床位
```

读取逻辑按列名取值，不依赖列顺序。后续可继续追加字段，例如：

```text
房间号,床号,失能等级,护理级别,备注,是否启用
```

只要不删除或改名现有必需字段，就不会影响当前院区识别和姓名、床位填充。代码也会优先读取 `失能等级`、`护理级别`、`养老院失能评估` 之一作为失能等级来源。

## 院区配置

院区配置位于 `config.json`。每个顶层 key 是院区代码，例如 `hf`、`jy`、`hk`、`nj`。

示例：

```json
{
  "hf": {
    "name": "合肥院区",
    "base_data_path": "C:\\Users\\Lenovo\\Desktop\\data\\合肥",
    "leave_bed_template_name": "leave_bed_analysis_template.json",
    "device_roster_name": "full_device_roster.csv",
    "crawler_account": "default",
    "tasks": ["1", "2", "3", "4", "5", "6", "7", "8"]
  }
}
```

字段说明：

- `name`：院区显示名，需要能和 `full_device_roster.csv` 的 `院区` 字段对应。
- `base_data_path`：该院区在 `data` 下的数据目录。
- `leave_bed_template_name`：离床分析 Excel 版式配置，放在 `assets/`。
- `device_roster_name`：统一设备总表，当前固定为 `full_device_roster.csv`。
- `crawler_account`：后台告警爬虫账号别名，对应本地 `assets/crawler_accounts.json`。
- `tasks`：该院区要执行的流水线步骤编号。

当前院区任务：

| 院区 | 代码 | 任务 |
| --- | --- | --- |
| 合肥 | `hf` | `1-8` |
| 姜堰 | `jy` | `1-3` |
| 香港 | `hk` | `1,2,3,6,10` |
| 南京 | `nj` | `1-3` |
| 盐城 | `yc` | `1-3` |
| 梧州 | `wz` | `1-3` |

各院区任务以 `config.json` 为准，README 仅同步说明。新增院区时，先把设备号补进 `assets/full_device_roster.csv`，再在 `config.json` 增加院区配置，最后同步 README。

## 流水线步骤

| 编号 | 步骤 |
| --- | --- |
| `raw_data` | 原始 CSV 归档检查 |
| `1` | 数据拆分 |
| `2` | 睡眠事件提取 |
| `3` | 智能切片 |
| `4` | 生成文本报告 |
| `5` | 图表生成 |
| `6` | 后台告警爬取 |
| `7` | 异常分析轨迹图 |
| `8` | Excel 报表合成 |
| `9` | 明细体征图表生成，Excel 不引用，耗时较长 |
| `10` | 离床预警叠加图 |

第 5 步会生成 Excel 需要的 `body_status` 离床状态图和 `accurate_leave_bed.json`。第 10 步根据后台离床预警时间点，读取前后 10 分钟 timeline，生成 `body_status` 与 `inbed_flag` 的叠加图。

## 离床分析模板

合肥离床分析 Excel 不再依赖旧的 `合肥院离床数据分析模板.xlsx`，当前读取轻量 JSON：

```text
assets/leave_bed_analysis_template.json
```

该 JSON 只保存版式配置，包括 sheet 名称、日期单元格、表头、列宽、数据行高、图片尺寸和离线/无人在床填充色。

老人、设备号、房间床位不写在 JSON 里，而是在运行时按当前院区从 `full_device_roster.csv` 自动填充。睡眠、离床、告警、诊断和图片仍按现有规则生成。

## 数据处理与数据分析

主流水线分成两层：

- 数据导入与解析：`pipeline/importing/raw_importer_v2.py` 扫描 `C:\Users\Lenovo\Downloads` 中的 CSV，按设备号识别院区，按有效睡眠日整理 rawdata；`pipeline/importing/data_split.py` 将呼吸心率 rawdata 解析为 timeline。
- 数据分析：`pipeline/analysis/` 中的模块按“院区 + 睡眠日”逐日消费 timeline、睡眠事件和后台告警数据，执行步骤 `2-10`。

识别依赖：

- 院区、设备号、姓名、床位：统一来自 `assets/full_device_roster.csv`。
- 文件类型：优先通过文件名识别 `*睡眠报告.csv` 与 `*呼吸心率.csv`，非标准文件名再通过 `iid`、`字段`、`描述` 等字段特征判断，公共识别逻辑位于 `pipeline/file_detector.py`。

新的 rawdata 整理规则：

- 呼吸心率 CSV 按外层 `时间` 分配睡眠日：当天 08:00 到次日 08:00 归为同一个睡眠日；只有检测到完整 24 小时窗口的睡眠日才写入 rawdata。
- 睡眠报告 CSV 按 `值` 里的 `sleep_start` 分配到对应睡眠日，只为已确认有效的呼吸心率睡眠日写入 rawdata。
- 同一源 CSV 可以拆成多个日期目录，例如 `rawdata\520`、`rawdata\521`。
- 整理完成后，源 CSV 会归档到 `C:\Users\Lenovo\Desktop\data\_raw_sources`。

同一院区、同一睡眠日需要同时有睡眠报告和呼吸心率两类 CSV，才会启动数据分析。边缘冗余日或缺少文件类型的日期只做 rawdata 归档，不自动跑分析。

## 运行方式

主流水线：

```bash
python main.py
```

测试跟踪独立流程：

```bash
python pipeline/test_tracker.py
```

失能周报独立流程：

```bash
python disability_weekreport/main.py
```

## 断点运行

状态表默认生成在：

```text
assets/pipeline_status.csv
```

一行表示一个“日期 + 院区”任务。只需要看 `状态` 列：

```text
状态 = 已完成  表示任务完成
状态 = 6       表示从第 6 步继续
状态 = 10      表示从第 10 步继续
```

状态表是运行产物，不提交到公开仓库。

## 测试跟踪独立流程

测试跟踪不接入 `main.py`，入口是：

```text
pipeline/test_tracker.py
```

它从 Downloads 读取测试跟踪 CSV，按 `config.json` 中已配置且能在设备总表匹配到的院区拆分归档到：

```text
C:\Users\Lenovo\Desktop\data\测试跟踪
```

`2.d.43` 文件只重命名归档；设备情况表会生成测试情况跟踪 `.xlsx`；`state_day = -1` 的记录会生成待补清单。

## 失能周报独立流程

失能周报入口是：

```text
disability_weekreport/main.py
```

它从 Downloads 识别周报 CSV，按设备总表拆分院区，生成各院区周报，并维护人工核实记录：

```text
disability_weekreport/verification_records.csv
```

输出目录：

```text
C:\Users\Lenovo\Desktop\data\失能周报数据
```

详细说明见 `disability_weekreport/README.md`。

## 后续重构方向

- 继续把路径和运行参数从源码迁入配置或命令行参数。
- 把 `full_device_roster.csv` 扩展为完整设备基础表，补充房间号、床号、失能等级等字段。
- 失能周报逐步完全依赖设备总表，不再依赖独立旧配置中的设备清单。
- 后台告警爬虫后续优先寻找接口替代 Selenium 翻页。
- 保持 `data` 输出结构与旧 `data` 基线一致，重构以结果一致性验收。
