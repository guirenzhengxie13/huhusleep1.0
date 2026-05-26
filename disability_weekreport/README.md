# 失能周报处理

这个文件夹是失能周报的正式入口，原来的 `weekreport` 只是临时开发目录。

## 文件说明

- `main.py`：从 Downloads 读取阿里云导出的周报 CSV，按设备号拆分院区，生成三院周报。
- `config.json`：设备号、老人姓名、护理等级、床位映射。
- `verification_records.csv`：自动维护的人工核实映射。每次运行前会扫描历史周报里的“误判”页，把已填写的核实内容沉淀到这里；生成新周报时会按设备号自动回填。
- `失能周报数据/`：可选历史备份目录。把旧周报放在这里，脚本也会扫描里面的 `*output/*.xlsx` 来吸收人工核实数据。

周报格式由 `main.py` 里的样式代码统一生成，不再复制历史 Excel 模板格式。

## 输出位置

所有生成文件统一写入：

```text
C:\Users\Lenovo\Desktop\data\失能周报数据
```

运行命令：

```powershell
python disability_weekreport\main.py
```
