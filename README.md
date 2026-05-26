# 睡眠监测数据处理项目

## 项目简介

本项目用于处理平台导出的睡眠监测 CSV，按院区和日期自动归档后生成中间数据、睡眠事件、离床片段、告警文件、图表和报表。主流程入口是 `main.py`，独立测试跟踪流程入口是 `pipeline/test_tracker.py`。

当前主要业务：

- 睡眠主流水线：处理睡眠报告、呼吸心率、后台告警和离床相关图表。
- 测试跟踪独立流程：处理测试情况跟踪表和 `2.d.43` 数据。
- 失能周报独立流程：位于 `disability_weekreport/`，不接入睡眠主流水线。

项目数据统一放在桌面 `data` 文件夹下，例如：

```text
C:\Users\Lenovo\Desktop\data
```

平台 CSV 默认从这里导入：

```text
C:\Users\Lenovo\Downloads
```

## 环境初始化

先安装 Python 依赖：

```bash
pip install -r requirements.txt
```

再准备 ChromeDriver。`assets/chromedriver.exe` 不进 Git，换电脑或 Chrome 更新后运行：

```bash
python tool/update_chromedriver.py
```

脚本会自动识别本机 Chrome 版本，检查并下载匹配的 ChromeDriver。旧驱动会备份为 `assets/chromedriver_backup_时间.exe`。

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

- `name`：院区显示名。
- `base_data_path`：该院区在桌面 `datatest` 下的数据目录；旧 `data` 暂作结果对照基线。
- `leave_bed_template_name`：离床分析 Excel 版式配置，放在 `assets/`，只保存表头、行列尺寸和图片布局。
- `device_roster_name`：统一设备总表，当前固定为 `assets/full_device_roster.csv`。
- `crawler_account`：后台告警爬虫账号别名，对应 `assets/crawler_accounts.json`。
- `tasks`：该院区要执行的流水线步骤编号。

当前院区任务：

| 院区 | 代码 | 任务 |
| --- | --- | --- |
| 合肥 | `hf` | `1-8` |
| 姜堰 | `jy` | `1-3` |
| 香港 | `hk` | `1,2,3,6,10` |
| 南京 | `nj` | `1-3` |

新增院区时，先把设备号补进 `assets/full_device_roster.csv`，再在 `config.json` 增加一段院区配置即可；目录不需要手动创建。

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

## 断点运行

状态表在：

```text
assets/pipeline_status.csv
```

一行表示一个“日期 + 院区”任务。只需要看 `状态`：

```text
状态=已完成  表示任务完成
状态=6       表示从第 6 步继续
状态=10      表示从第 10 步继续
```

程序每次启动时会先读取状态表，优先执行未完成任务，并自动跳过断点之前的步骤。想手动调试某一步，就把对应行的 `状态` 改成步骤编号；跑完后程序会自动改回 `已完成`。

## 后台告警爬取

后台告警是第 6 步，依赖 Selenium、Chrome 和 `assets/chromedriver.exe`。爬虫账号在：

```text
assets/crawler_accounts.json
```

每个院区通过 `config.json` 的 `crawler_account` 选择账号。香港使用独立账号，因为不同账号能看到不同院区。告警 CSV 会保存到对应院区 `warn` 目录。

## 测试跟踪独立流程

测试跟踪不接入 `main.py`，入口是：

```text
pipeline/test_tracker.py
```

它从 Downloads 读取测试跟踪 CSV，按合肥、姜堰、南京拆分归档到：

```text
C:\Users\Lenovo\Desktop\data\测试跟踪
```

`2.d.43` 文件只重命名归档；设备情况表会生成测试情况跟踪 `.xlsx`；`state_day = -1` 的记录会生成待补清单。

## 后续优化方向

- 将 `IMPORT_DIR`、项目根目录等硬编码路径迁入配置文件。
- 给 `main.py` 增加命令行参数，减少直接改源码。
- 继续优化告警爬虫，优先寻找后台接口替代 Selenium 翻页。
- 将第 10 步离床预警叠加图的样式和输出规则沉淀为正式报表附件。
- 整理 `assets` 中各院区映射文件，补齐姜堰、南京、香港的长期维护规范。
