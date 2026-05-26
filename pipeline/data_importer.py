import csv
import glob
import json
import logging
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pytz

from config import Config
from utils import build_device_to_location_from_roster

DEFAULT_IMPORT_DIR = r"C:\Users\Lenovo\Downloads"
CONFIG_FILE_PATH = "config.json"
SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
SLEEP_DAY_OFFSET_HOURS = 12

FILE_TYPES = {
    "sleep_report": {
        "filename_suffix": "睡眠报告.csv",
        "field_markers": ("sleep-report-generate", "睡眠报告", "sleep_start", "sleep_events"),
    },
    "vital_track": {
        "filename_suffix": "呼吸心率.csv",
        "field_markers": ("sleep-track-data", "睡眠跟踪", "gettime", "heart_rate", "respiratory_rate"),
    },
}


def load_config_data(config_file_path=CONFIG_FILE_PATH):
    with open(config_file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _business_date_from_timestamp(raw_ts):
    ts = int(float(raw_ts))
    if ts >= 1000000000000:
        ts = ts / 1000

    dt = datetime.fromtimestamp(ts, tz=SHANGHAI_TZ)
    dt = dt - timedelta(hours=SLEEP_DAY_OFFSET_HOURS)
    return dt.strftime("%Y-%m-%d")


def _datetime_from_timestamp(raw_ts):
    ts = int(float(raw_ts))
    if ts >= 1000000000000:
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=SHANGHAI_TZ)


def _normalize_header(header):
    return [str(item).strip().lstrip("\ufeff") for item in header]


def _read_sample_rows(csv_path, max_rows=300):
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        try:
            header = _normalize_header(next(reader))
        except StopIteration:
            return [], []

        for _, row in zip(range(max_rows), reader):
            if row:
                rows.append(row)
    return header, rows


def _row_value(header, row, column_name, default=""):
    try:
        idx = header.index(column_name)
    except ValueError:
        return default
    return row[idx] if idx < len(row) else default


def _detect_file_type(header, rows):
    score = Counter()
    for row in rows[:80]:
        row_text = ",".join(row)
        for file_type, spec in FILE_TYPES.items():
            for marker in spec["field_markers"]:
                if marker in row_text:
                    score[file_type] += 1

    if not score:
        return None
    file_type, count = score.most_common(1)[0]
    return file_type if count > 0 else None


def _extract_dates(header, rows, file_type=None):
    dates = []
    datetimes = []
    timestamp_pattern = re.compile(
        r"(?:gettime|start|go_bed|leave_bed|sleep_start|sleep_end)[^0-9]{0,40}(\d{10,13})"
    )

    for row in rows[:120]:
        outer_time = _row_value(header, row, "时间")
        if outer_time:
            try:
                dates.append(_business_date_from_timestamp(outer_time))
                datetimes.append(_datetime_from_timestamp(outer_time))
            except Exception:
                pass

        value = _row_value(header, row, "值")
        for ts in timestamp_pattern.findall(value):
            try:
                dates.append(_business_date_from_timestamp(ts))
                datetimes.append(_datetime_from_timestamp(ts))
            except Exception:
                continue

    if file_type == "vital_track" and datetimes:
        # 呼吸心率下载常按“前一天到今天”导出，文件中的最新自然日是结束日；
        # 流水线的睡眠日应使用结束日前一天，例如 5/2 文件归到 5/1。
        latest_dt = max(datetimes)
        return (latest_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    if not dates:
        return None
    return Counter(dates).most_common(1)[0][0]


def _extract_vital_track_date(csv_path):
    latest_dt = None
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        try:
            header = _normalize_header(next(reader))
            time_idx = header.index("时间")
        except (StopIteration, ValueError):
            return None

        for row in reader:
            if time_idx >= len(row):
                continue
            try:
                dt = _datetime_from_timestamp(row[time_idx])
            except Exception:
                continue
            if latest_dt is None or dt > latest_dt:
                latest_dt = dt

    if latest_dt is None:
        return None
    return (latest_dt - timedelta(days=1)).strftime("%Y-%m-%d")


def _extract_device_ids(header, rows):
    device_ids = []
    for row in rows:
        device_id = _row_value(header, row, "设备ID")
        if device_id:
            device_ids.append(device_id)
    return device_ids


def build_device_location_index(config_data, project_root):
    ensure_base_dirs(config_data)
    roster_path = os.path.join(project_root, "assets", "full_device_roster.csv")
    device_to_location = build_device_to_location_from_roster(config_data, roster_path)
    if not device_to_location:
        logging.warning("设备总表未提供可用设备号，院区识别可能失败: %s", roster_path)
    return device_to_location


def ensure_base_dirs(config_data):
    for location_config in config_data.values():
        base_data_path = location_config.get("base_data_path")
        if not base_data_path:
            continue
        for folder in ["", "rawdata", "timeline", "output", "warn"]:
            os.makedirs(os.path.join(base_data_path, folder), exist_ok=True)


def _detect_location(device_ids, device_to_location):
    counter = Counter()
    for device_id in device_ids:
        location_code = device_to_location.get(device_id)
        if location_code:
            counter[location_code] += 1

    if not counter:
        return None
    return counter.most_common(1)[0][0]


def inspect_csv(csv_path, device_to_location):
    header, rows = _read_sample_rows(csv_path)
    if not rows:
        return None

    file_type = _detect_file_type(header, rows)
    if file_type == "vital_track":
        target_date = _extract_vital_track_date(csv_path) or _extract_dates(header, rows, file_type)
    else:
        target_date = _extract_dates(header, rows, file_type)
    device_ids = _extract_device_ids(header, rows)
    location_code = _detect_location(device_ids, device_to_location)

    if not file_type or not target_date or not location_code:
        logging.warning(
            "⚠️ 无法完整识别 CSV: %s | 类型=%s 日期=%s 院区=%s",
            os.path.basename(csv_path),
            file_type,
            target_date,
            location_code,
        )
        return None

    return {
        "source_path": csv_path,
        "file_type": file_type,
        "target_date": target_date,
        "location_code": location_code,
        "device_count": len(set(device_ids)),
    }


def _target_path_for(info, config_data):
    location_config = config_data[info["location_code"]]
    config = Config(location_config, info["target_date"])
    date_str = info["target_date"].replace("-", "")
    suffix = FILE_TYPES[info["file_type"]]["filename_suffix"]
    filename = f"{date_str}{suffix}"
    return config.RAW_DATA_DIR, os.path.join(config.RAW_DATA_DIR, filename)


def _has_raw_pair(raw_dir):
    if not os.path.exists(raw_dir):
        return False
    csv_names = [
        name for name in os.listdir(raw_dir)
        if name.endswith(".csv") and not name.startswith("sorted_")
    ]
    has_sleep = any("睡眠报告" in name for name in csv_names)
    has_vital = any("呼吸心率" in name for name in csv_names)
    return has_sleep and has_vital


def _move_file(source_path, target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    if os.path.exists(target_path):
        logging.info("✅ 目标文件已存在，跳过移动: %s", target_path)
        return False

    shutil.move(source_path, target_path)
    logging.info("✂️ 已归档: %s -> %s", os.path.basename(source_path), target_path)
    return True


def discover_and_import(import_dir=DEFAULT_IMPORT_DIR, config_file_path=CONFIG_FILE_PATH, project_root=None):
    if project_root is None:
        project_root = os.getcwd()

    if not os.path.exists(import_dir):
        raise FileNotFoundError(f"找不到导入目录: {import_dir}")

    config_data = load_config_data(config_file_path)
    device_to_location = build_device_location_index(config_data, project_root)

    csv_files = glob.glob(os.path.join(import_dir, "*.csv"))
    csv_files = [path for path in csv_files if not os.path.basename(path).startswith("sorted_")]
    if not csv_files:
        logging.info("📭 导入目录没有待识别 CSV: %s", import_dir)
        return []

    groups = defaultdict(dict)
    for csv_path in csv_files:
        info = inspect_csv(csv_path, device_to_location)
        if not info:
            continue
        key = (info["location_code"], info["target_date"])
        current = groups[key].get(info["file_type"])
        if current is None or os.path.getmtime(info["source_path"]) > os.path.getmtime(current["source_path"]):
            groups[key][info["file_type"]] = info
        logging.info(
            "🔎 识别 CSV: %s | 院区=%s 日期=%s 类型=%s 设备数=%s",
            os.path.basename(csv_path),
            info["location_code"],
            info["target_date"],
            info["file_type"],
            info["device_count"],
        )

    jobs = []
    for (location_code, target_date), files_by_type in groups.items():
        missing_types = set(FILE_TYPES) - set(files_by_type)
        location_config = config_data[location_code]
        config = Config(location_config, target_date)
        had_pair_before = _has_raw_pair(config.RAW_DATA_DIR)

        if missing_types and not had_pair_before:
            logging.warning(
                "⚠️ %s %s 缺少文件类型: %s，暂不启动流水线",
                location_code,
                target_date,
                ", ".join(sorted(missing_types)),
            )
            continue

        moved_files = []
        for file_type, info in files_by_type.items():
            _, target_path = _target_path_for(info, config_data)
            if _move_file(info["source_path"], target_path):
                moved_files.append(target_path)

        if moved_files or (not had_pair_before and _has_raw_pair(config.RAW_DATA_DIR)):
            jobs.append({
                "location_code": location_code,
                "target_date": target_date,
                "raw_dir": config.RAW_DATA_DIR,
                "moved_files": moved_files,
            })

    jobs.sort(key=lambda item: (item["target_date"], item["location_code"]))
    return jobs


def ensure_raw_data(config, config_data, import_dir=DEFAULT_IMPORT_DIR, project_root=None):
    if _has_raw_pair(config.RAW_DATA_DIR):
        logging.info("✅ 检测到本地原始数据已齐全，跳过导入: %s", config.RAW_DATA_DIR)
        return

    logging.warning("⚠️ %s 原始数据不完整，尝试从导入目录自动识别归档。", config.RAW_DATA_DIR)
    jobs = discover_and_import(import_dir, CONFIG_FILE_PATH, project_root)
    matched = [
        job for job in jobs
        if job["location_code"] == config.LOCATION_CODE and job["target_date"] == config.FILE_DATE
    ]

    if not matched and not _has_raw_pair(config.RAW_DATA_DIR):
        raise FileNotFoundError(f"未能为 {config.LOCATION_CODE} {config.FILE_DATE} 准备完整原始 CSV")
