import csv
import json
import logging
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import pytz

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from utils import build_device_to_location_from_roster

DEFAULT_IMPORT_DIR = r"C:\Users\Lenovo\Downloads"
CONFIG_FILE_PATH = "config.json"
SOURCE_ARCHIVE_DIR_NAME = "_raw_sources"
SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
SLEEP_DAY_START_HOUR = 8
COMPLETE_TOLERANCE_SECONDS = 5 * 60
INCOMPLETE_DEVICE_LIMIT = 5

FILE_TYPES = {
    "sleep_report": {
        "filename_suffix": "睡眠报告.csv",
        "iid": "2.D.10",
        "field": "sleep-report-generate",
        "description": "睡眠报告",
    },
    "vital_track": {
        "filename_suffix": "呼吸心率.csv",
        "iid": "2.D.30",
        "field": "sleep-track-data",
        "description": "睡眠跟踪",
    },
}


def load_config_data(config_file_path=CONFIG_FILE_PATH):
    with open(config_file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_base_dirs(config_data):
    for location_config in config_data.values():
        base_data_path = location_config.get("base_data_path")
        if not base_data_path:
            continue
        for folder in ["", "rawdata", "timeline", "output", "warn"]:
            os.makedirs(os.path.join(base_data_path, folder), exist_ok=True)


def build_device_location_index(config_data, project_root):
    ensure_base_dirs(config_data)
    roster_path = os.path.join(project_root, "assets", "full_device_roster.csv")
    device_to_location = build_device_to_location_from_roster(config_data, roster_path)
    if not device_to_location:
        logging.warning("设备总表未提供可用设备号，院区识别可能失败: %s", roster_path)
    return device_to_location


def _normalize_header(header):
    return [str(item).strip().lstrip("\ufeff") for item in header]


def _header_indexes(header):
    return {name: index for index, name in enumerate(_normalize_header(header))}


def _row_value(indexes, row, column_name, default=""):
    idx = indexes.get(column_name)
    if idx is None or idx >= len(row):
        return default
    return str(row[idx]).strip()


def _timestamp_seconds(raw_ts):
    ts = int(float(raw_ts))
    if ts >= 1000000000000:
        ts = ts // 1000
    return ts


def _datetime_from_timestamp(raw_ts):
    return datetime.fromtimestamp(_timestamp_seconds(raw_ts), tz=SHANGHAI_TZ)


def _sleep_day_from_timestamp(raw_ts):
    dt = _datetime_from_timestamp(raw_ts)
    return (dt - timedelta(hours=SLEEP_DAY_START_HOUR)).strftime("%Y-%m-%d")


def _parse_json_value(value):
    text = (value or "").strip()
    if not text:
        return None

    for candidate in (text, text.strip('"').replace('\\"', '"')):
        try:
            data = json.loads(candidate)
            if isinstance(data, str):
                return json.loads(data)
            return data
        except json.JSONDecodeError:
            continue
    return None


def _sleep_report_payload(value):
    data = _parse_json_value(value)
    if not isinstance(data, dict):
        return None

    inner = data.get("data")
    if isinstance(inner, str):
        inner_data = _parse_json_value(inner)
        if isinstance(inner_data, dict):
            return inner_data
    return data


def _sleep_report_day_from_row(indexes, row):
    payload = _sleep_report_payload(_row_value(indexes, row, "值"))
    if not isinstance(payload, dict) or payload.get("sleep_start") is None:
        return None
    return _sleep_day_from_timestamp(payload["sleep_start"])


def _sleep_day_bounds(sleep_day):
    start = SHANGHAI_TZ.localize(datetime.strptime(f"{sleep_day} 08:00:00", "%Y-%m-%d %H:%M:%S"))
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def _month_day_folder(target_date):
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    return f"{dt.month}{dt.day}"


def _target_path_for(location_code, target_date, file_type, config_data):
    base_data_path = config_data[location_code]["base_data_path"]
    raw_dir = os.path.join(base_data_path, "rawdata", _month_day_folder(target_date))
    date_str = target_date.replace("-", "")
    suffix = FILE_TYPES[file_type]["filename_suffix"]
    return raw_dir, os.path.join(raw_dir, f"{date_str}{suffix}")


def _has_raw_pair(raw_dir):
    if not os.path.exists(raw_dir):
        return False
    csv_names = [
        name for name in os.listdir(raw_dir)
        if name.endswith(".csv") and not name.startswith("sorted_")
    ]
    return any("睡眠报告" in name for name in csv_names) and any("呼吸心率" in name for name in csv_names)


def _source_archive_root(config_data):
    base_paths = [
        str(location_config.get("base_data_path", "")).rstrip("\\/")
        for location_config in config_data.values()
        if location_config.get("base_data_path")
    ]
    if not base_paths:
        return os.path.join(os.path.expanduser("~"), "Desktop", "datatest", SOURCE_ARCHIVE_DIR_NAME)

    parent_paths = [os.path.dirname(path) for path in base_paths]
    try:
        output_root = os.path.commonpath(parent_paths)
    except ValueError:
        output_root = parent_paths[0]
    return os.path.join(output_root, SOURCE_ARCHIVE_DIR_NAME)


def _available_archive_path(archive_root, source_path):
    os.makedirs(archive_root, exist_ok=True)
    base_name = os.path.basename(source_path)
    target_path = os.path.join(archive_root, base_name)
    if not os.path.exists(target_path):
        return target_path

    stem, ext = os.path.splitext(base_name)
    suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    return os.path.join(archive_root, f"{stem}_{suffix}{ext}")


def _archive_source_file(source_path, archive_root):
    target_path = _available_archive_path(archive_root, source_path)
    shutil.move(source_path, target_path)
    logging.info("源 CSV 已归档: %s -> %s", os.path.basename(source_path), target_path)
    return target_path


def _read_header(csv_path):
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        try:
            return _normalize_header(next(reader))
        except StopIteration:
            return []


def _detect_file_type(csv_path, sample_limit=80):
    header = _read_header(csv_path)
    indexes = _header_indexes(header)
    if "设备ID" not in indexes or "时间" not in indexes:
        return None, header, indexes

    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        scores = defaultdict(int)
        for _, row in zip(range(sample_limit), reader):
            iid = _row_value(indexes, row, "iid")
            field = _row_value(indexes, row, "字段")
            description = _row_value(indexes, row, "描述")
            if iid == FILE_TYPES["vital_track"]["iid"] or field == FILE_TYPES["vital_track"]["field"]:
                scores["vital_track"] += 1
            if iid == FILE_TYPES["sleep_report"]["iid"] or field == FILE_TYPES["sleep_report"]["field"] or description == FILE_TYPES["sleep_report"]["description"]:
                scores["sleep_report"] += 1

    if not scores:
        return None, header, indexes
    file_type = max(scores.items(), key=lambda item: item[1])[0]
    return file_type, header, indexes


def _new_day_summary(line_no, timestamp_sec):
    return {
        "start_line": line_no,
        "end_line": line_no,
        "row_count": 0,
        "min_time": timestamp_sec,
        "max_time": timestamp_sec,
    }


def _update_day_summary(summary, line_no, timestamp_sec):
    summary["end_line"] = line_no
    summary["row_count"] += 1
    summary["min_time"] = min(summary["min_time"], timestamp_sec)
    summary["max_time"] = max(summary["max_time"], timestamp_sec)


def _is_complete_day(day_summary, sleep_day):
    start_ts, end_ts = _sleep_day_bounds(sleep_day)
    return (
        day_summary["min_time"] <= start_ts + COMPLETE_TOLERANCE_SECONDS
        and day_summary["max_time"] >= end_ts - COMPLETE_TOLERANCE_SECONDS
    )


def _finish_device_block(blocks, current):
    if current is not None:
        current["end_line"] = max(current["end_line"], current["start_line"])
        blocks.append(current)


def _evaluate_valid_sleep_days(blocks):
    all_days = sorted({day for block in blocks for day in block["sleep_days"]})
    valid_days = set()
    day_results = {}

    for sleep_day in all_days:
        incomplete_count = 0
        checked_devices = []
        valid_device = ""
        for block in blocks:
            day_summary = block["sleep_days"].get(sleep_day)
            is_complete = bool(day_summary and _is_complete_day(day_summary, sleep_day))
            checked_devices.append({
                "device_id": block["device_id"],
                "complete": is_complete,
                "row_count": day_summary["row_count"] if day_summary else 0,
                "min_time": day_summary["min_time"] if day_summary else None,
                "max_time": day_summary["max_time"] if day_summary else None,
            })
            if is_complete:
                valid_days.add(sleep_day)
                valid_device = block["device_id"]
                break
            incomplete_count += 1
            if incomplete_count >= INCOMPLETE_DEVICE_LIMIT:
                break

        day_results[sleep_day] = {
            "valid": sleep_day in valid_days,
            "valid_device": valid_device,
            "checked_device_count": len(checked_devices),
            "checked_devices": checked_devices,
        }

    return valid_days, day_results


def _build_vital_split_index(csv_path, header, indexes, device_to_location):
    blocks = []
    current = None

    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            line_no = reader.line_num
            device_id = _row_value(indexes, row, "设备ID")
            raw_time = _row_value(indexes, row, "时间")
            if not device_id or not raw_time:
                continue
            try:
                timestamp_sec = _timestamp_seconds(raw_time)
                sleep_day = _sleep_day_from_timestamp(raw_time)
            except Exception:
                continue

            if current is None or device_id != current["device_id"]:
                _finish_device_block(blocks, current)
                current = {
                    "device_id": device_id,
                    "location_code": device_to_location.get(device_id, ""),
                    "start_line": line_no,
                    "end_line": line_no,
                    "row_count": 0,
                    "sleep_days": {},
                }

            current["end_line"] = line_no
            current["row_count"] += 1
            day_summary = current["sleep_days"].setdefault(sleep_day, _new_day_summary(line_no, timestamp_sec))
            _update_day_summary(day_summary, line_no, timestamp_sec)

    _finish_device_block(blocks, current)
    valid_days, day_results = _evaluate_valid_sleep_days(blocks)
    return {
        "source_path": csv_path,
        "source_file": os.path.basename(csv_path),
        "file_type": "vital_track",
        "header": header,
        "header_line": 1,
        "line_number_basis": "csv.reader.line_num",
        "device_blocks": blocks,
        "sleep_days": day_results,
        "valid_sleep_days": sorted(valid_days),
    }, valid_days


def _open_target_writer(target_path, header, writers, written_counts):
    writer_info = writers.get(target_path)
    if writer_info:
        return writer_info[0]

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    should_write_header = not os.path.exists(target_path) or os.path.getsize(target_path) == 0
    f = open(target_path, "a", encoding="utf-8-sig", newline="")
    writer = csv.writer(f)
    if should_write_header:
        writer.writerow(header)
    writers[target_path] = (writer, f)
    written_counts.setdefault(target_path, 0)
    return writer


def _write_rows_by_day(csv_path, header, indexes, file_type, config_data, device_to_location, valid_sleep_days):
    writers = {}
    written_counts = {}
    written_meta = {}
    target_cache = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                device_id = _row_value(indexes, row, "设备ID")
                location_code = device_to_location.get(device_id)
                if not location_code:
                    continue

                try:
                    if file_type == "vital_track":
                        target_date = _sleep_day_from_timestamp(_row_value(indexes, row, "时间"))
                    else:
                        target_date = _sleep_report_day_from_row(indexes, row)
                except Exception:
                    continue
                if not target_date:
                    continue

                if target_date not in valid_sleep_days:
                    continue

                target_key = (location_code, target_date, file_type)
                target_path = target_cache.get(target_key)
                if target_path is None:
                    _, target_path = _target_path_for(location_code, target_date, file_type, config_data)
                    target_cache[target_key] = target_path
                    written_meta[target_path] = {
                        "location_code": location_code,
                        "target_date": target_date,
                        "file_type": file_type,
                        "path": target_path,
                    }
                writer = _open_target_writer(target_path, header, writers, written_counts)
                writer.writerow(row)
                written_counts[target_path] += 1
    finally:
        for _, f in writers.values():
            f.close()

    return [
        {**written_meta[path], "rows": rows}
        for path, rows in written_counts.items()
    ]


def _write_split_index_sidecar(index_data, archived_source_path):
    index_data = dict(index_data)
    index_data["archived_source_path"] = archived_source_path
    sidecar_path = f"{archived_source_path}.split_index.json"
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    logging.info("呼吸心率分割索引已写入: %s", sidecar_path)
    return sidecar_path


def discover_and_import(import_dir=DEFAULT_IMPORT_DIR, config_file_path=CONFIG_FILE_PATH, project_root=None):
    if project_root is None:
        project_root = os.getcwd()
    if not os.path.exists(import_dir):
        raise FileNotFoundError(f"找不到导入目录: {import_dir}")

    config_data = load_config_data(config_file_path)
    device_to_location = build_device_location_index(config_data, project_root)
    csv_paths = [
        os.path.join(import_dir, name)
        for name in sorted(os.listdir(import_dir))
        if name.lower().endswith(".csv") and not name.startswith("sorted_")
    ]
    if not csv_paths:
        logging.info("导入目录没有待识别 CSV: %s", import_dir)
        return []

    vital_sources = []
    report_sources = []
    recognized_sources = []
    all_valid_sleep_days = set()

    for csv_path in csv_paths:
        file_type, header, indexes = _detect_file_type(csv_path)
        if not file_type:
            logging.warning("跳过 CSV，未识别文件类型或缺少必要列: %s", os.path.basename(csv_path))
            continue

        recognized_sources.append(csv_path)
        if file_type == "vital_track":
            split_index, valid_days = _build_vital_split_index(csv_path, header, indexes, device_to_location)
            vital_sources.append({
                "path": csv_path,
                "header": header,
                "indexes": indexes,
                "split_index": split_index,
            })
            all_valid_sleep_days.update(valid_days)
            logging.info(
                "识别呼吸心率 CSV: %s | 有效睡眠日=%s",
                os.path.basename(csv_path),
                ",".join(sorted(valid_days)) or "无",
            )
        else:
            report_sources.append({"path": csv_path, "header": header, "indexes": indexes})
            logging.info("识别睡眠报告 CSV: %s", os.path.basename(csv_path))

    if not recognized_sources:
        return []

    written_files = []
    for source in vital_sources:
        written_files.extend(_write_rows_by_day(
            source["path"],
            source["header"],
            source["indexes"],
            "vital_track",
            config_data,
            device_to_location,
            all_valid_sleep_days,
        ))

    for source in report_sources:
        written_files.extend(_write_rows_by_day(
            source["path"],
            source["header"],
            source["indexes"],
            "sleep_report",
            config_data,
            device_to_location,
            all_valid_sleep_days,
        ))

    archive_root = _source_archive_root(config_data)
    archived_paths = {}
    for source_path in recognized_sources:
        archived_paths[source_path] = _archive_source_file(source_path, archive_root)

    for source in vital_sources:
        _write_split_index_sidecar(source["split_index"], archived_paths[source["path"]])

    jobs = []
    touched_jobs = sorted({(item["location_code"], item["target_date"]) for item in written_files})
    for location_code, target_date in touched_jobs:
        location_config = dict(config_data[location_code])
        location_config["code"] = location_code
        config = Config(location_config, target_date)
        job_files = [
            item["path"]
            for item in written_files
            if item["location_code"] == location_code and item["target_date"] == target_date
        ]
        if _has_raw_pair(config.RAW_DATA_DIR):
            jobs.append({
                "location_code": location_code,
                "target_date": target_date,
                "raw_dir": config.RAW_DATA_DIR,
                "written_files": job_files,
            })
        else:
            logging.warning("%s %s 原始数据不完整，暂不启动流水线", location_code, target_date)

    jobs.sort(key=lambda item: (item["target_date"], item["location_code"]))
    return jobs


def ensure_raw_data(config, config_data, import_dir=DEFAULT_IMPORT_DIR, project_root=None):
    if _has_raw_pair(config.RAW_DATA_DIR):
        logging.info("检测到本地原始数据已齐全，跳过导入: %s", config.RAW_DATA_DIR)
        return

    logging.warning("%s 原始数据不完整，尝试从导入目录自动识别归档。", config.RAW_DATA_DIR)
    jobs = discover_and_import(import_dir, CONFIG_FILE_PATH, project_root)
    matched = [
        job for job in jobs
        if job["location_code"] == config.LOCATION_CODE and job["target_date"] == config.FILE_DATE
    ]
    if not matched and not _has_raw_pair(config.RAW_DATA_DIR):
        raise FileNotFoundError(f"未能为 {config.LOCATION_CODE} {config.FILE_DATE} 准备完整原始 CSV")
