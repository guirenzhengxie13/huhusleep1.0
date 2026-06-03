# huhusleep1.0 当前风险点总结（给 Codex 更新用）

> 目标分支：`test`  
> 仓库：`guirenzhengxie13/huhusleep1.0`  
> 目的：整理当前项目中较明显的维护风险、硬编码、隐式假设和文档不同步点，方便 Codex 按优先级逐项修复。  
> 注意：本文件主要用于代码更新任务，不要求一次性全部改完，建议先处理 P0/P1。

---

## 0. 总体判断

当前项目已经具备比较清晰的三条流程：

1. 睡眠主流水线：`main.py`
2. 测试跟踪独立流程：`pipeline/test_tracker.py`
3. 失能周报独立流程：`disability_weekreport/main.py`

整体架构方向是对的：  
`config.json` + `Config` + `full_device_roster.csv` + `pipeline_status.csv` 已经形成了一个可持续维护的数据处理系统。

当前主要风险不是“不能跑”，而是：

- 部分依赖没有写入 `requirements.txt`
- 部分文件识别仍依赖“最大/最小 CSV”等隐式假设
- 个别院区名、路径、任务范围存在硬编码
- README 与实际配置已经轻微不同步
- 测试跟踪和主流程的院区范围不一致
- 部分模块缺少更明确的输入输出约束和异常提示

---

## 1. P0：补全 requirements.txt 依赖

### 问题

`requirements.txt` 当前只包含：

```txt
pytz==2024.1
openpyxl==3.1.2
matplotlib==3.8.4
selenium==4.19.0
```

但项目代码实际使用了：

- `pandas`
- `numpy`

例如：

- `pipeline/analysis/abnormal_analysis.py` 使用 `pandas`
- `pipeline/analysis/leave_bed_overlay_debug.py` 使用 `pandas`
- `disability_weekreport/main.py` 使用 `pandas` 和 `numpy`

### 影响

新电脑、虚拟环境、Codex 环境、CI 环境中直接执行可能出现：

```txt
ModuleNotFoundError: No module named 'pandas'
ModuleNotFoundError: No module named 'numpy'
```

### 建议修改

更新 `requirements.txt`，至少加入：

```txt
pandas
numpy
```

如果希望版本更稳定，可以固定版本，例如：

```txt
pandas>=2.0
numpy>=1.24
```

### 涉及文件

- `requirements.txt`

### 验收标准

- 新环境执行 `pip install -r requirements.txt` 后：
  - `python main.py` 不因缺包中断
  - `python pipeline/test_tracker.py --dry-run` 不因缺包中断
  - `python disability_weekreport/main.py` 不因缺包中断

---

## 2. P0：data_split.py 不应再靠“最大 CSV”识别呼吸心率文件

### 问题

`pipeline/importing/data_split.py` 中 `get_latest_csv_file()` 实际是：

- 扫描 rawdata 目录
- 找所有非 `sorted_` 开头的 CSV
- 按文件大小倒序排序
- 取最大的 CSV

当前逻辑默认“呼吸心率 CSV 一定最大”。

### 影响

如果某天睡眠报告 CSV 异常变大，或者 rawdata 目录混入其他 CSV，就可能误把非呼吸心率文件当作 timeline 输入，导致：

- timeline 为空
- 数据拆分结果异常
- 后续睡眠事件、切片、图表全部失败

### 建议修改

优先级建议：

1. 优先按文件名匹配：`*呼吸心率.csv`
2. 如果文件名不标准，再按字段识别：
   - 表头包含：`设备ID`、`时间`、`值`
   - 行内容中 `iid == 2.D.30` 或 `字段 == sleep-track-data`
3. 如果识别到多个候选文件，按日期或文件名规则选择，并打印明确日志
4. 如果识别不到，抛出明确异常

### 推荐新增函数

```python
def find_vital_track_csv(raw_data_dir):
    """在 rawdata 目录中明确查找呼吸心率 CSV，不再依赖文件大小。"""
    ...
```

### 涉及文件

- `pipeline/importing/data_split.py`
- 可复用 `pipeline/importing/raw_importer_v2.py` 中的识别逻辑

### 验收标准

- rawdata 同时存在睡眠报告和呼吸心率时，稳定选择呼吸心率
- rawdata 中混入其他 CSV 时，不误选
- 找不到呼吸心率时，错误信息明确说明缺少哪类文件

---

## 3. P0：sleep_evt.py 不应再靠“最小 CSV”识别睡眠报告文件

### 问题

`pipeline/analysis/sleep_evt.py` 中 `get_smallest_csv()` 当前逻辑是：

- 扫描 rawdata 目录
- 找所有 CSV
- 按文件大小升序排序
- 取最小的 CSV

当前默认“睡眠报告 CSV 一定最小”。

### 影响

如果 rawdata 中混入小体积 CSV，或者睡眠报告体积异常，就会误选输入文件，导致：

- 无法提取 `sleep_start`
- 无法提取 `sleep_end`
- 无法提取 `sleep_events`
- 后续离床切片和图表为空

### 建议修改

优先级建议：

1. 优先按文件名匹配：`*睡眠报告.csv`
2. 如果文件名不标准，再按字段识别：
   - `iid == 2.D.10`
   - 或 `字段 == sleep-report-generate`
   - 或 `描述 == 睡眠报告`
3. 如果识别失败，抛出明确异常

### 推荐新增函数

```python
def find_sleep_report_csv(raw_data_dir):
    """在 rawdata 目录中明确查找睡眠报告 CSV，不再依赖文件大小。"""
    ...
```

### 涉及文件

- `pipeline/analysis/sleep_evt.py`
- 可复用 `pipeline/importing/raw_importer_v2.py` 中的识别逻辑

### 验收标准

- rawdata 同时存在两类 CSV 时，稳定选择睡眠报告
- rawdata 中混入其他 CSV 时，不误选
- 找不到睡眠报告时，错误信息明确说明缺少哪类文件

---

## 4. P1：README 与 config.json 院区配置不同步

### 问题

README 的院区任务表中列出：

- 合肥 `hf`
- 姜堰 `jy`
- 香港 `hk`
- 南京 `nj`
- 梧州 `wz`

但实际 `config.json` 里还包含：

- 盐城 `yc`

### 影响

后续交接时容易误以为盐城没有接入主流水线。

### 建议修改

更新 README 的院区任务表，加入：

```md
| 盐城 | `yc` | `1-3` |
```

并说明当前各院区任务由 `config.json` 控制，README 只是说明文档。

### 涉及文件

- `README.md`
- `config.json`

### 验收标准

- README 院区表与 `config.json` 一致
- 新增院区时有明确说明：
  1. 先更新 `assets/full_device_roster.csv`
  2. 再更新 `config.json`
  3. 最后同步 README

---

## 5. P1：Excel 输出文件名硬编码为“合肥院”

### 问题

`pipeline/analysis/excel.py` 中输出文件名写死为：

```python
save_excel_path = os.path.join(config.BASE_DATA_PATH, f'合肥院离床数据分析{config.DATE_STR}晚.xlsx')
```

当前只有合肥执行第 8 步，所以暂时没出问题。

### 影响

如果后续其他院区也开启第 8 步，输出文件名仍然是“合肥院”，会造成：

- 文件名错误
- 交接理解错误
- 多院区报表混淆

### 建议修改

改成动态院区名，例如：

```python
location_name = config.LOCATION_CONFIG.get("name", config.LOCATION_CODE).replace("院区", "")
save_excel_path = os.path.join(
    config.BASE_DATA_PATH,
    f'{location_name}院离床数据分析{config.DATE_STR}晚.xlsx'
)
```

注意：如果 `name` 已经包含“院”或“院区”，需要避免重复拼接成“合肥院院”。

更稳妥写法：

```python
display_name = config.LOCATION_CONFIG.get("name", config.LOCATION_CODE)
display_name = display_name.replace("院区", "")
if not display_name.endswith("院"):
    display_name += "院"

save_excel_path = os.path.join(
    config.BASE_DATA_PATH,
    f'{display_name}离床数据分析{config.DATE_STR}晚.xlsx'
)
```

### 涉及文件

- `pipeline/analysis/excel.py`

### 验收标准

- 合肥仍输出：`合肥院离床数据分析YYYYMMDD晚.xlsx`
- 如果未来南京开启第 8 步，应输出：`南京院离床数据分析YYYYMMDD晚.xlsx`
- 不出现“合肥院”硬编码

---

## 6. P1：测试跟踪流程院区范围写死，只支持 hf/jy/nj

### 问题

`pipeline/test_tracker.py` 中写死：

```python
TRACKED_LOCATION_CODES = {"hf", "jy", "nj"}
```

但主流程 `config.json` 已经包括：

- `hf`
- `jy`
- `hk`
- `nj`
- `yc`
- `wz`

### 影响

如果 Downloads 中存在香港、盐城、梧州的测试跟踪 CSV，即使设备总表中有对应设备，也会被测试跟踪流程忽略。

### 建议修改

提供两种方案：

#### 方案 A：直接跟随 config.json

默认支持 `config.json` 中所有院区：

```python
TRACKED_LOCATION_CODES = None
```

构建映射时不再过滤固定集合。

#### 方案 B：在 config.json 中增加测试跟踪开关

例如：

```json
"hf": {
  "name": "合肥院区",
  "test_tracker_enabled": true
}
```

然后 `test_tracker.py` 读取这个字段决定是否启用。

### 推荐

建议先用方案 A，最简单。  
如果后续确实有些院区不需要测试跟踪，再做方案 B。

### 涉及文件

- `pipeline/test_tracker.py`
- 可选：`config.json`
- 可选：`README.md`

### 验收标准

- 设备总表中属于香港、盐城、梧州的测试跟踪 CSV 能被识别
- 如果需要排除某院区，README 中说明排除机制

---

## 7. P1：主流程文件类型识别逻辑分散，建议抽公共工具

### 问题

当前文件类型识别逻辑分散在多个地方：

- `raw_importer_v2.py` 有 `_detect_file_type()`
- `data_split.py` 独立解析 `2.D.30`
- `sleep_evt.py` 通过最小文件猜测睡眠报告
- `test_tracker.py` 有自己的 `_detect_data_type()`
- `disability_weekreport/main.py` 有自己的 `is_weekreport_csv()`

### 影响

同一种文件类型判断规则散落多个模块，后续平台字段变更时，需要多处修改，容易漏改。

### 建议修改

新增一个公共模块，例如：

```text
pipeline/file_detector.py
```

集中提供：

```python
detect_sleep_file_type(csv_path) -> "sleep_report" | "vital_track" | None
find_sleep_report_csv(raw_data_dir)
find_vital_track_csv(raw_data_dir)

detect_test_tracking_type(csv_path) -> "device_status" | "identity_2d43" | None
is_weekreport_csv(csv_path)
```

先不要求一次性重构所有流程，可以先把 P0 的两个函数放进去。

### 涉及文件

- 新增：`pipeline/file_detector.py`
- 修改：`pipeline/importing/data_split.py`
- 修改：`pipeline/analysis/sleep_evt.py`
- 后续可修改：`pipeline/test_tracker.py`
- 后续可修改：`disability_weekreport/main.py`

### 验收标准

- `data_split.py` 和 `sleep_evt.py` 不再根据文件大小猜测类型
- 文件识别规则集中在一个模块，后续维护更容易

---

## 8. P1：README 应明确三条流程的边界

### 问题

README 已经说明三条流程，但还可以更明确地区分：

1. 主睡眠流水线：`main.py`
2. 测试跟踪：`pipeline/test_tracker.py`
3. 失能周报：`disability_weekreport/main.py`

目前 README 对整体说明是有的，但给 Codex 或新人接手时，还缺少“不要混在一起改”的边界提醒。

### 影响

后续容易把测试跟踪或失能周报误接入 `main.py`，造成流程耦合。

### 建议修改

在 README 增加“流程边界”小节：

```md
## 流程边界

- `main.py` 只负责睡眠主流水线。
- `pipeline/test_tracker.py` 是测试跟踪独立流程，不由 `main.py` 调用。
- `disability_weekreport/main.py` 是失能周报独立流程，不由 `main.py` 调用。
- 三条流程共享 `assets/full_device_roster.csv`，但输出目录和运行入口独立。
```

### 涉及文件

- `README.md`

### 验收标准

- README 明确写出三条流程的入口、输入、输出、是否接入主流水线

---

## 9. P2：Windows 绝对路径较多，后续可逐步配置化

### 问题

项目中存在多处 Windows 绝对路径，例如：

```text
C:\Users\Lenovo\Downloads
C:\Users\Lenovo\Desktop\data
C:\Users\Lenovo\Desktop\data\测试跟踪
```

这些路径符合当前电脑环境，但不利于换电脑、CI、多人协作。

### 影响

换电脑后需要全局搜索修改路径。  
Codex 或其他自动化环境中无法直接运行。

### 建议修改

短期不强制改，因为当前业务运行环境就是这台 Windows 电脑。  
中期建议：

1. 保留默认路径
2. 支持环境变量覆盖
3. 支持命令行参数覆盖

例如：

```python
IMPORT_DIR = os.environ.get("HUHUSLEEP_IMPORT_DIR", r"C:\Users\Lenovo\Downloads")
DATA_ROOT = os.environ.get("HUHUSLEEP_DATA_ROOT", r"C:\Users\Lenovo\Desktop\data")
```

### 涉及文件

- `main.py`
- `config.json`
- `pipeline/test_tracker.py`
- `disability_weekreport/main.py`

### 验收标准

- 当前默认路径不变
- 用户可以通过环境变量切换数据根目录
- README 说明环境变量用法

---

## 10. P2：matplotlib 字体依赖 SimHei，非中文 Windows 环境可能缺字

### 问题

多个绘图模块写死：

```python
plt.rcParams['font.sans-serif'] = ['SimHei']
```

涉及：

- `pipeline/analysis/plotter.py`
- `pipeline/analysis/abnormal_analysis.py`
- `pipeline/analysis/leave_bed_overlay_debug.py`

### 影响

如果系统没有 SimHei 字体，图表中文可能乱码或出现字体警告。

### 建议修改

增加字体 fallback：

```python
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
```

或者封装到公共函数：

```python
def setup_matplotlib_chinese_font():
    ...
```

### 涉及文件

- `pipeline/analysis/plotter.py`
- `pipeline/analysis/abnormal_analysis.py`
- `pipeline/analysis/leave_bed_overlay_debug.py`
- 可选新增：`utils_plot.py`

### 验收标准

- 没有 SimHei 时仍能尽量显示中文
- 不影响当前 Windows 环境

---

## 11. P2：raw_importer_v2.py 对“完整 24 小时窗口”的判断可补充日志

### 问题

`raw_importer_v2.py` 会判断有效睡眠日：  
呼吸心率 CSV 按 08:00 到次日 08:00 判断是否完整，容差 5 分钟。逻辑本身合理。

但如果某天没有进入流水线，用户可能只看到“原始数据不完整”，不知道具体原因是：

- 哪台设备不完整
- 最早时间是多少
- 最晚时间是多少
- 差多少分钟
- 是否只有睡眠报告没有呼吸心率
- 是否只有呼吸心率没有睡眠报告

### 影响

排查 Downloads 原始数据时不够直观。

### 建议修改

在以下场景增加更明确日志：

1. `valid_sleep_days` 为空时
2. `_has_raw_pair()` 为 False 时
3. 只写入了某一类文件时

可以输出类似：

```txt
[导入诊断] 2026-05-20 合肥：呼吸心率存在，但未达到完整 08:00-次日08:00 窗口
[导入诊断] 已检查设备数=5，最接近完整设备=xxx，范围=08:03:12~07:58:01
[导入诊断] 睡眠报告缺失：未发现 *睡眠报告.csv
```

### 涉及文件

- `pipeline/importing/raw_importer_v2.py`

### 验收标准

- 自动模式没有生成 job 时，日志能说明原因
- 不影响正常导入流程

---

## 12. P2：异常处理中过多 except Exception: continue，建议至少记录 debug 日志

### 问题

多个模块中存在大量：

```python
except Exception:
    continue
```

例如：

- `sleep_evt.py`
- `slicer.py`
- `data_split.py`
- `excel.py`

### 影响

当某条记录解析失败时，当前逻辑会静默跳过。  
这对业务“不中断”是好的，但对排查数据格式问题不友好。

### 建议修改

保留不中断行为，但增加低噪声日志统计：

```python
bad_rows += 1
```

最后汇总：

```txt
解析完成：成功 xxx 条，跳过异常 yyy 条
```

对于关键异常，可以使用：

```python
logging.debug("跳过异常行: %s", e)
```

不要每行都打 warning，避免日志爆炸。

### 涉及文件

- `pipeline/importing/data_split.py`
- `pipeline/analysis/sleep_evt.py`
- `pipeline/analysis/slicer.py`
- `pipeline/analysis/excel.py`

### 验收标准

- 正常运行日志不刷屏
- 解析异常有汇总数量
- 出问题时可通过 debug 日志定位

---

## 13. P2：失能周报仍保留旧 config regions，需明确优先级

### 问题

`disability_weekreport/config.json` 中仍然有大量旧式 `regions` 设备列表。  
而 `disability_weekreport/main.py` 已经开始从 `assets/full_device_roster.csv` 构建设备列表。

### 影响

维护者可能不清楚到底应该改：

- `assets/full_device_roster.csv`
- 还是 `disability_weekreport/config.json`

### 当前判断

代码里 `build_regions_from_roster()` 已经优先从 `full_device_roster.csv` 构建院区设备列表，但 `config.json` 中的旧 `regions` 仍用于补充护理级别映射。

### 建议修改

在 `disability_weekreport/config.json` 或 README 中明确：

- 新设备统一维护在 `assets/full_device_roster.csv`
- `disability_weekreport/config.json` 中的 `regions` 仅作为旧兼容/护理级别补充
- 后续应逐步迁移护理级别到 `full_device_roster.csv`

### 涉及文件

- `disability_weekreport/main.py`
- `disability_weekreport/config.json`
- `README.md`

### 验收标准

- 文档明确“设备主数据唯一来源”
- 后续新增设备不需要同时改两处

---

## 14. P2：建议增加 docs 目录，沉淀交接文档

### 问题

当前 README 已经比较详细，但项目已经有三条流程，后续 README 会越来越长。

### 建议新增

```text
docs/
├─ 01_项目总览.md
├─ 02_主流水线说明.md
├─ 03_测试跟踪流程说明.md
├─ 04_失能周报流程说明.md
└─ 05_常见问题与恢复方式.md
```

### 建议内容

#### 01_项目总览.md

- 项目解决的问题
- 三条流程边界
- 设备总表说明
- 输入输出目录

#### 02_主流水线说明.md

- `python main.py`
- 自动模式/单日模式/步进模式
- 1~10 步说明
- 状态表续跑方式

#### 03_测试跟踪流程说明.md

- 支持哪些 CSV
- 输出到哪里
- `state_day=-1` 待补清单

#### 04_失能周报流程说明.md

- 输入字段要求
- 院区拆分
- 误判/误报率逻辑
- 人工核实记录

#### 05_常见问题与恢复方式.md

- 缺依赖
- 缺 chromedriver
- 缺 crawler_accounts.json
- Excel 文件被占用
- Downloads 没识别到 CSV
- 状态表卡住怎么继续

### 涉及文件

- 新增 `docs/`

### 验收标准

- 新人只看 docs 能知道怎么运行、怎么排查、怎么新增院区

---

## 15. 建议 Codex 执行顺序

### 第一批：必须优先修

1. 补全 `requirements.txt`
2. `data_split.py` 明确识别呼吸心率 CSV
3. `sleep_evt.py` 明确识别睡眠报告 CSV
4. README 同步盐城院区

### 第二批：提高可维护性

5. Excel 输出文件名去硬编码
6. 测试跟踪院区范围改为跟随配置
7. 抽出 `pipeline/file_detector.py`
8. README 增加三条流程边界说明

### 第三批：增强鲁棒性

9. 路径支持环境变量覆盖
10. matplotlib 中文字体 fallback
11. raw_importer 增加导入诊断日志
12. 异常行跳过增加汇总统计
13. 失能周报旧配置优先级文档化
14. 新增 docs 目录

---

## 16. 给 Codex 的推荐任务提示词

可以直接把下面这段发给 Codex：

```md
请基于当前仓库 test 分支，按本风险总结逐项修复。优先处理 P0 和 P1：

1. 补全 requirements.txt，加入 pandas/numpy。
2. 修改 pipeline/importing/data_split.py，不再用最大 CSV 猜呼吸心率文件，改为明确识别 *呼吸心率.csv 或 2.D.30/sleep-track-data。
3. 修改 pipeline/analysis/sleep_evt.py，不再用最小 CSV 猜睡眠报告文件，改为明确识别 *睡眠报告.csv 或 2.D.10/sleep-report-generate。
4. 更新 README.md，使院区任务表与 config.json 一致，补充 yc 盐城院区。
5. 修改 pipeline/analysis/excel.py，去掉“合肥院”硬编码，按 config.LOCATION_CONFIG 动态生成院区名。
6. 修改 pipeline/test_tracker.py，不要写死 TRACKED_LOCATION_CODES = {"hf", "jy", "nj"}，默认跟随 config.json 中可识别的院区。
7. 如改动较多，请优先新增公共文件识别模块 pipeline/file_detector.py，避免重复识别逻辑。
8. 保持当前默认 Windows 路径和原有输出结构不变，避免破坏现有业务运行。
9. 每个改动请尽量保留向后兼容，并补充必要日志。
10. 修改完成后，请给出变更摘要和手动验证步骤。
```

---

## 17. 不建议 Codex 当前立即大改的内容

以下内容暂时不建议一口气重构：

- 不建议把所有 Windows 路径一次性改成跨平台路径，容易破坏当前本机运行。
- 不建议把三条流程强行合并到 `main.py`。
- 不建议删除 `disability_weekreport/config.json` 的旧 `regions`，因为可能仍承担护理级别兼容作用。
- 不建议大量改 Excel 样式逻辑，除非有明确样例对照。
- 不建议改业务判定规则，例如离床时间、告警窗口、`eftv_times > 5` 等，除非确认需求变更。

---

## 18. 最终目标

这轮更新的目标不是做大型重构，而是先把当前项目从“能跑”提升到“更稳、更容易交接、更不容易误识别文件”。

优先保证：

- 原有输出结构不变
- 当前 Windows 电脑默认路径不变
- 现有业务结果不变
- 文件识别更可靠
- 新环境安装依赖更完整
- README 与实际代码一致
