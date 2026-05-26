# 睡眠监测数据处理项目

本项目用于处理平台导出的睡眠监测 CSV，按院区和日期自动归档后生成中间数据、睡眠事件、离床片段、告警文件、图表和报表。当前仓库是重构期公开备份仓库，目标是逐步摆脱旧 Excel/TXT 依赖，同时保持输出结果形态一致。

当前主要业务：

- 睡眠主流水线：处理睡眠报告、呼吸心率、后台告警、离床图表和合肥离床分析 Excel。
- 测试跟踪独立流程：处理测试情况跟踪表和 `2.d.43` 数据。
- 失能周报独立流程：位于 `disability_weekreport/`，不接入睡眠主流水线。

## 当前路径约定

重构期输出统一写入：

```text
C:\Users\Lenovo\Desktop\datatest
```

旧结果对照基线保留在：

```text
C:\Users\Lenovo\Desktop\data
```

平台 CSV 默认从这里导入：

```text
C:\Users\Lenovo\Downloads
```

## 公开仓库注意事项

这个仓库不提交本地账号、驱动和运行结果：

- `assets/crawler_accounts.json`：本地爬虫账号文件，不进 Git。
- `assets/chromedriver.exe`：本地 ChromeDriver，不进 Git。
- `assets/pipeline_status.csv`：运行状态表，不进 Git。
- `assets/旧依赖/`、`最新设备下载/`：旧表格依赖和平台导出备份，不进 Git。
- `datatest/`、`data/`：运行输出目录，不进 Git。

首次运行前，如需后台告警爬取，请在本地创建 `assets/crawler_accounts.json`，格式如下：

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

## 环境初始化

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

准备 ChromeDriver：

```bash
python tool/update_chromedriver.py
```

脚本会自动识别本机 Chrome 版本，下载匹配的 `assets/chromedriver.exe`。该文件只保存在本地。

## 统一设备总表

当前全项目设备基础信息统一来自：

```text
assets/full_device_roster.csv
```

现有必需字段：

```text
院区,设备号,老人姓名,房间床位
```

读取逻辑按列名取值，不依赖列顺序。后续可以继续追加字段，例如：

```text
房间号,床号,失能等级,护理级别,备注,是否启用
```

只要不删除或改名现有四个字段，就不会影响当前院区识别和姓名/床位填充。代码已经预留读取 `失能等级`、`护理级别`、`养老院失能评估` 之一作为失能等级来源。

## 院区配置

院区配置在 `config.json`。每个顶层 key 是院区代码，例如 `hf`、`jy`、`hk`、`nj`。

示例：

```json
{
  "hf": {
    "name": "合肥院区",
    "base_data_path": "C:\\Users\\Lenovo\\Desktop\\datatest\\合肥",
    "leave_bed_template_name": "leave_bed_analysis_template.json",
    "device_roster_name": "full_device_roster.csv",
    "crawler_account": "default",
    "tasks": ["1", "2", "3", "4", "5", "6", "7", "8"]
  }
}
```

字段说明：

- `name`：院区显示名，需要能和 `full_device_roster.csv` 的 `院区` 字段对应。
- `base_data_path`：该院区在 `datatest` 下的数据目录。
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

新增院区时，先把设备号补进 `assets/full_device_roster.csv`，再在 `config.json` 增加院区配置。

## 离床分析 Excel 模板配置

合肥离床分析 Excel 不再依赖旧的 `合肥院离床数据分析模板.xlsx`。当前改为读取轻量 JSON：

```text
assets/leave_bed_analysis_template.json
```

该 JSON 只保存版式配置：

- sheet 名称
- 日期单元格
- 表头
- 列宽
- 数据行高
- 图片尺寸和偏移
- 离线/无人在床填充色

老人、设备号、房间床位不写在 JSON 里，而是运行时按当前院区从 `full_device_roster.csv` 自动填入。睡眠、离床、告警、诊断和图片仍按现有规则生成。

## 流水线步骤

| 编号 | 步骤 |
| --- | --- |
| 1 | 数据拆分 |
| 2 | 睡眠事件提取 |
| 3 | 智能切片 |
| 4 | 生成文本报告 |
| 5 | 图表生成 |
| 6 | 后台告警爬取 |
| 7 | 异常分析轨迹图 |
| 8 | Excel 报表合成 |
| 9 | 明细体征图表生成，Excel 不引用，耗时较长 |
| 10 | 离床预警叠加图 |

第 5 步生成 Excel 需要的 `body_status` 离床状态图和 `accurate_leave_bed.json`。第 10 步根据后台离床预警时间点，读取前后 10 分钟 timeline，生成 `body_status` 与 `inbed_flag` 的叠加图。

## 自动识别与归档

`pipeline/data_importer.py` 会扫描 `C:\Users\Lenovo\Downloads` 中的 CSV，自动识别院区、日期和文件类型。

识别依赖：

- 院区、设备号、姓名、床位：统一来自 `assets/full_device_roster.csv`。
- 文件类型：睡眠报告 CSV 与呼吸心率 CSV 的字段特征。

同一院区、同一日期需要同时有睡眠报告和呼吸心率两类 CSV，才会启动主流水线。重构期归档和输出都在桌面 `datatest` 对应院区目录下。

## 运行方式

主流程：

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

状态表默认在本地生成：

```text
assets/pipeline_status.csv
```

一行表示一个“日期 + 院区”任务。只需要看 `状态`：

```text
状态=已完成  表示任务完成
状态=6       表示从第 6 步继续
状态=10      表示从第 10 步继续
```

该状态表是运行产物，不提交到公开仓库。

## 测试跟踪独立流程

测试跟踪不接入 `main.py`，入口是：

```text
pipeline/test_tracker.py
```

它从 Downloads 读取测试跟踪 CSV，按合肥、姜堰、南京拆分归档到：

```text
C:\Users\Lenovo\Desktop\datatest\测试跟踪
```

`2.d.43` 文件只重命名归档；设备情况表会生成测试情况跟踪 `.xlsx`；`state_day = -1` 的记录会生成待补清单。

## 后续重构方向

- 继续把路径和运行参数从源码迁入配置或命令行参数。
- 把 `full_device_roster.csv` 扩展为完整设备基础表，补充房间号、床号、失能等级等字段。
- 失能周报逐步改为完全依赖设备总表，不再依赖独立旧配置中的设备清单。
- 后台告警爬虫后续优先寻找接口替代 Selenium 翻页。
- 保持 `datatest` 输出结构与旧 `data` 基线一致，重构以结果一致性验收。
