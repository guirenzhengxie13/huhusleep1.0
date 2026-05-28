import os
import csv
import json
import logging
import argparse
import shutil
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils import mkdir_recursive

ATTRIBUTE_NAME = "time,heart_rate,respiratory_rate,body_movement,move_state,body_status,body_position,inbed_flag,cluster_id,cluster_x,cluster_y,cluster_num,cluster_id,cluster_x,cluster_y,cluster_num\n"
DEFAULT_STANDALONE_IMPORT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
DEFAULT_STANDALONE_OUTPUT_ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "datatest", "timeline_standalone")
STANDALONE_REQUIRED_COLUMNS = ["设备ID", "iid", "字段", "描述", "时间", "值"]
SLEEP_TRACK_IID = "2.D.30"
SLEEP_TRACK_FIELD = "sleep-track-data"

def get_range_of_sleep(date_str, start_time_str, duration_hours):
    start_datetime = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M:%S")
    start_timestamp = int(start_datetime.timestamp())
    end_timestamp = start_timestamp + duration_hours * 3600
    
    end_datetime = datetime.fromtimestamp(end_timestamp)
    file_date = end_datetime.strftime("%Y-%m-%d")
    
    return start_timestamp, end_timestamp, file_date

def get_latest_csv_file(directory):
    csv_files = []
    if not os.path.exists(directory):
        return None
        
    for file in os.listdir(directory):
        if file.endswith('.csv') and not file.startswith('sorted_'):
            file_path = os.path.join(directory, file)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                csv_files.append((file_size, file))
    if csv_files:
        csv_files.sort(key=lambda x: x[0], reverse=True)
        return csv_files[0][1]
    return None

def business_window_from_timestamp(timestamp_sec):
    """按 08:00 分界计算业务文件夹和 timeline 文件日期。"""
    business_date = (datetime.fromtimestamp(timestamp_sec) - timedelta(hours=8)).date()
    file_date = business_date + timedelta(days=1)
    month_day_folder = f"{business_date.month}{business_date.day}"
    return month_day_folder, file_date.strftime("%Y-%m-%d")

def _normalize_json_text(value):
    text = (value or "").strip()
    if not text:
        return ""
    return text.strip('"').replace('\\"', '"')

def _get_list_value(values, index, default=0):
    if isinstance(values, list) and index < len(values):
        return values[index]
    return default

def _cluster_to_text(cluster, index):
    if not isinstance(cluster, list) or index >= len(cluster):
        return ""
    items = cluster[index]
    if not isinstance(items, list):
        return ""
    return ",".join(item.strip('"') for item in items if isinstance(item, str))

def _standalone_header_indexes(header):
    normalized_header = [cell.strip().lstrip("\ufeff") for cell in header]
    if not all(column in normalized_header for column in STANDALONE_REQUIRED_COLUMNS):
        return None
    return {column: normalized_header.index(column) for column in STANDALONE_REQUIRED_COLUMNS}

def _standalone_row_value(row, indexes, column):
    index = indexes[column]
    return row[index].strip() if index < len(row) else ""

def _parse_standalone_track_row(row, indexes):
    iid = _standalone_row_value(row, indexes, "iid")
    field = _standalone_row_value(row, indexes, "字段")
    if iid != SLEEP_TRACK_IID and field != SLEEP_TRACK_FIELD:
        return None

    device_id = _standalone_row_value(row, indexes, "设备ID")
    if not device_id:
        return None

    data_str = _normalize_json_text(_standalone_row_value(row, indexes, "值"))
    if not data_str:
        return None

    data = json.loads(data_str)
    timestamp_ms = data.get("gettime")
    if timestamp_ms is None:
        return None

    timestamp_sec = int(float(timestamp_ms)) // 1000
    return device_id, timestamp_sec, data

def _write_standalone_track_rows(writer, timestamp_sec, data):
    heart_rate = data.get("heart_rate", [0] * 6)
    respiratory_rate = data.get("respiratory_rate", [0] * 6)
    body_movement = data.get("body_movement", [0] * 6)
    move_state = data.get("move_state", [0] * 6)
    body_status = data.get("body_status", [0] * 6)
    body_position = data.get("body_position", [0] * 6)
    inbed_flag = data.get("inbed_flag", [0] * 6)
    cluster = data.get("cluster", [[]] * 6)

    for index in range(6):
        time_fmt = datetime.fromtimestamp(timestamp_sec + index).strftime("%Y-%m-%d %H:%M:%S")
        writer.write(
            f"{time_fmt},"
            f"{_get_list_value(heart_rate, index)},"
            f"{_get_list_value(respiratory_rate, index)},"
            f"{_get_list_value(body_movement, index)},"
            f"{_get_list_value(move_state, index)},"
            f"{_get_list_value(body_status, index)},"
            f"{_get_list_value(body_position, index)},"
            f"{_get_list_value(inbed_flag, index)},"
            f"{_cluster_to_text(cluster, index)}\n"
        )

def _sort_and_dedupe_timeline_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [line for line in f.readlines() if line.strip()]

    data_lines = [line for line in lines[1:] if "," in line]
    latest_by_time = {}
    for line in data_lines:
        time_key = line.split(",", 1)[0]
        latest_by_time[time_key] = line

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(ATTRIBUTE_NAME)
        for time_key in sorted(latest_by_time):
            f.write(latest_by_time[time_key])

def _open_standalone_writer(path, writers):
    writer = writers.get(path)
    if writer:
        return writer

    os.makedirs(os.path.dirname(path), exist_ok=True)
    should_write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    writer = open(path, "a", encoding="utf-8", newline="")
    if should_write_header:
        writer.write(ATTRIBUTE_NAME)
    writers[path] = writer
    return writer

def process_standalone_csv(csv_path, timeline_root, dry_run=False):
    stats = {
        "source_path": csv_path,
        "valid_rows": 0,
        "invalid_rows": 0,
        "devices": set(),
        "date_folders": set(),
        "output_paths": set(),
    }

    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        indexes = _standalone_header_indexes(header)
        if indexes is None:
            return None, "表头不符合原始呼吸心率 CSV 格式"

        writers = {}
        try:
            for row in reader:
                try:
                    parsed = _parse_standalone_track_row(row, indexes)
                    if not parsed:
                        continue

                    device_id, timestamp_sec, data = parsed
                    month_day_folder, file_date = business_window_from_timestamp(timestamp_sec)
                    stats["valid_rows"] += 1
                    stats["devices"].add(device_id)
                    stats["date_folders"].add(month_day_folder)

                    if dry_run:
                        continue

                    output_dir = os.path.join(timeline_root, month_day_folder, device_id)
                    output_path = os.path.join(output_dir, f"{device_id}_{file_date}.csv")
                    stats["output_paths"].add(output_path)
                    writer = _open_standalone_writer(output_path, writers)
                    _write_standalone_track_rows(writer, timestamp_sec, data)
                except Exception:
                    stats["invalid_rows"] += 1
        finally:
            for writer in writers.values():
                writer.close()

    if stats["valid_rows"] == 0:
        return None, "没有可解析的 2.D.30 sleep-track-data 数据"

    return stats, None

def run_standalone(import_dir=DEFAULT_STANDALONE_IMPORT_DIR, output_root=DEFAULT_STANDALONE_OUTPUT_ROOT, dry_run=False):
    timeline_root = os.path.join(output_root, "timeline")
    if not os.path.exists(import_dir):
        raise FileNotFoundError(f"导入目录不存在: {import_dir}")

    if not dry_run:
        if os.path.exists(timeline_root):
            shutil.rmtree(timeline_root)
        os.makedirs(timeline_root, exist_ok=True)

    results = []
    skipped = []
    csv_files = [
        os.path.join(import_dir, filename)
        for filename in sorted(os.listdir(import_dir))
        if filename.lower().endswith(".csv")
    ]

    for csv_path in csv_files:
        result, reason = process_standalone_csv(csv_path, timeline_root, dry_run=dry_run)
        if result is None:
            skipped.append((csv_path, reason))
            logging.info("跳过 CSV: %s | %s", os.path.basename(csv_path), reason)
            continue
        results.append(result)
        logging.info(
            "识别 CSV: %s | 原始记录 %s 条 | 设备 %s 台 | 日期 %s",
            os.path.basename(csv_path),
            result["valid_rows"],
            len(result["devices"]),
            ", ".join(sorted(result["date_folders"])),
        )

    if not dry_run:
        output_paths = sorted({path for result in results for path in result["output_paths"]})
        for path in output_paths:
            _sort_and_dedupe_timeline_file(path)

    summary = {
        "import_dir": import_dir,
        "output_root": output_root,
        "timeline_root": timeline_root,
        "files_total": len(csv_files),
        "files_parsed": len(results),
        "files_skipped": len(skipped),
        "raw_rows": sum(result["valid_rows"] for result in results),
        "invalid_rows": sum(result["invalid_rows"] for result in results),
        "devices": sorted({device for result in results for device in result["devices"]}),
        "date_folders": sorted({date for result in results for date in result["date_folders"]}),
        "output_files": sorted({path for result in results for path in result["output_paths"]}),
        "skipped": skipped,
    }
    return summary

def print_standalone_summary(summary, dry_run=False):
    mode = "DRY-RUN" if dry_run else "DONE"
    print(f"[{mode}] data_split 独立解析")
    print(f"导入目录: {summary['import_dir']}")
    print(f"输出目录: {summary['timeline_root']}")
    print(f"CSV 总数: {summary['files_total']} | 已解析: {summary['files_parsed']} | 跳过: {summary['files_skipped']}")
    print(f"可解析原始记录: {summary['raw_rows']} | 解析异常记录: {summary['invalid_rows']}")
    print(f"设备数: {len(summary['devices'])} | 日期文件夹: {', '.join(summary['date_folders']) or '无'}")
    if not dry_run:
        print(f"生成 timeline 文件: {len(summary['output_files'])}")
    if summary["skipped"]:
        print("跳过文件:")
        for csv_path, reason in summary["skipped"]:
            print(f"  - {os.path.basename(csv_path)}: {reason}")

def run(config):
    """外部调用的主入口"""
    raw_data_file = get_latest_csv_file(config.RAW_DATA_DIR)
    if not raw_data_file:
        raise FileNotFoundError(f"未找到原始 CSV 文件: {config.RAW_DATA_DIR}")

    input_file = os.path.join(config.RAW_DATA_DIR, raw_data_file)
    logging.info("使用已整理的原始 CSV: %s", input_file)
    current_dev_id = None
    start_timestamp, end_timestamp, file_date = get_range_of_sleep(config.FILE_DATE, config.START_TIME, config.DURATION_TIME)
    current_device_rows = []
    line_count = 0

    def flush_current_device():
        if not current_dev_id:
            return

        output_path = os.path.join(config.TIMELINE_DIR, current_dev_id)
        mkdir_recursive(output_path)
        save_file = os.path.join(output_path, f"{current_dev_id}_{file_date}.csv")

        current_device_rows.sort(key=lambda item: item[0])
        with open(save_file, 'w', encoding='utf-8') as sp:
            sp.write(ATTRIBUTE_NAME)
            for _, line in current_device_rows:
                sp.write(line)

    logging.info("开始处理时序数据，请稍候...")
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as fp:
        reader = csv.reader(fp)
        for row in reader:
            line_count += 1

            if len(row) < 6:
                continue
            dev_id = row[0]
            data_str = row[5]
            if 'gettime' not in data_str:
                continue

            if dev_id != current_dev_id:
                flush_current_device()
                current_dev_id = dev_id
                current_device_rows = []

            try:
                data_str = data_str.strip('"""').replace('\\"', '"')
                data = json.loads(data_str)
                time_str = data.get('gettime', 0) // 1000

                if time_str < start_timestamp or time_str > end_timestamp:
                    continue

                heart_rate = data.get('heart_rate', [0]*6)
                respiratory_rate = data.get('respiratory_rate', [0]*6)
                body_movement = data.get('body_movement', [0]*6)
                move_state = data.get('move_state', [0]*6)
                body_status = data.get('body_status', [0]*6)
                body_position = data.get('body_position', [0]*6)
                inbed_flag = data.get('inbed_flag', [0]*6)
                cluster = data.get('cluster', [[]]*6)

                cluster_data = []
                for i in range(6):
                    if i < len(cluster):
                        group = [c.strip('"') for c in cluster[i] if isinstance(c, str)]
                        cluster_data.append(','.join(group))
                    else:
                        cluster_data.append('')

                for j in range(6):
                    ct = datetime.fromtimestamp(time_str + j)
                    time_fmt = ct.strftime("%Y-%m-%d %H:%M:%S")
                    line = f"{time_fmt},{heart_rate[j]},{respiratory_rate[j]},{body_movement[j]},{move_state[j]},{body_status[j]},{body_position[j]},{inbed_flag[j]},{cluster_data[j]}\n"
                    current_device_rows.append((time_str + j, line))

            except Exception:
                continue

    flush_current_device()
        
    logging.info(f"✅ 时序解析完毕，共处理了 {line_count} 行原始数据")
    logging.info(f"📂 结果保存在：{config.TIMELINE_DIR}")

def main():
    parser = argparse.ArgumentParser(description="独立解析 Downloads 原始呼吸心率 CSV 为 timeline")
    parser.add_argument("--import-dir", default=DEFAULT_STANDALONE_IMPORT_DIR, help="输入 CSV 文件夹，默认 Downloads")
    parser.add_argument("--output-root", default=DEFAULT_STANDALONE_OUTPUT_ROOT, help="独立输出根目录")
    parser.add_argument("--dry-run", action="store_true", help="只扫描汇总，不写 timeline 文件")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    summary = run_standalone(import_dir=args.import_dir, output_root=args.output_root, dry_run=args.dry_run)
    print_standalone_summary(summary, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
