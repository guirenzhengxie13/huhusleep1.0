# 失能周报处理

这个目录是失能周报的独立入口，不接入根目录的睡眠主流水线。

## 文件说明

- `main.py`：从 Downloads 读取阿里云导出的周报 CSV，按设备号拆分院区，并生成各院区周报。
- `config.json`：保留历史周报配置，当前主要用于护理级别兼容映射。
- `verification_records.csv`：自动维护的人工核实映射。每次运行前会扫描历史周报里的“误判”页，把已填写的核实内容沉淀到这里；生成新周报时会按设备号自动回填。
- `失能周报数据/`：可选历史备份目录。把旧周报放在这里，脚本也会扫描其中的 `*output/*.xlsx` 来吸收人工核实数据。

周报格式由 `main.py` 中的样式代码统一生成，不再复制历史 Excel 模板格式。

## 数据来源

设备、老人、院区和失能等级优先来自根目录统一设备总表：

```text
assets/full_device_roster.csv
```

脚本会从以下目录识别周报 CSV：

```text
C:\Users\Lenovo\Downloads
```

识别到混合院区 CSV 时，会按设备号拆分成各院区输入文件。

## 输出位置

所有生成文件统一写入：

```text
C:\Users\Lenovo\Desktop\datatest\失能周报数据
```

每天会生成两个目录：

```text
MDD\
MDDoutput\
```

其中 `MDD` 是运行当天的月日，例如 `526`。

## 运行命令

在项目根目录执行：

```powershell
python disability_weekreport\main.py
```

运行前请确认本机已安装 `pandas`、`numpy` 和 `openpyxl`。
