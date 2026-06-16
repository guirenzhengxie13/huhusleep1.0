import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config


OUTPUT_DIR_NAME = "timeline_markers"
SUMMARY_FILENAME = "timeline_markers.csv"
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
STATE_COLUMNS = ("move_state", "body_status", "inbed_flag")
REQUIRED_COLUMNS = ("time", *STATE_COLUMNS)
MIN_MARKER_SECONDS = 300
MAX_CONTINUOUS_GAP_SECONDS = 10

MARKER_FIELDNAMES = [
    "院区",
    "院区代码",
    "日期",
    "设备号",
    "事件类型",
    "开始行号",
    "结束行号",
    "持续秒数",
    "持续分钟",
    "开始时间",
    "结束时间",
]


def _load_config_data(config_path=DEFAULT_CONFIG_PATH):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_config(config_data, location_code, target_date):
    location_config = dict(config_data[location_code])
    location_config["code"] = location_code
    return Config(location_config, target_date)


def _month_day_to_date(value):
    text = str(value).strip()
    if re.fullmatch(r"\d{2,4}", text):
        now_year = datetime.now().year
        if len(text) == 2:
            month = int(text[:1])
            day = int(text[1:])
        else:
            month = int(text[:-2])
            day = int(text[-2:])
        return f"{now_year}-{month:02d}-{day:02d}"
    return text


def _normalize_binary(value):
    text = str(value).strip()
    if text in ("", "0", "0.0"):
        return 0
    try:
        return 0 if float(text) == 0 else 1
    except ValueError:
        return 1


def _row_value(row, indexes, column, default=""):
    index = indexes.get(column)
    if index is None or index >= len(row):
        return default
    return str(row[index]).strip()


def _parse_time(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _timeline_files(config):
    if not os.path.exists(config.TIMELINE_DIR):
        return
    for device_id in sorted(os.listdir(config.TIMELINE_DIR)):
        device_dir = os.path.join(config.TIMELINE_DIR, device_id)
        if not os.path.isdir(device_dir):
            continue
        for filename in sorted(os.listdir(device_dir)):
            if filename.lower().endswith(".csv"):
                yield device_id, os.path.join(device_dir, filename)


def _read_first_last_times(csv_path):
    first_time = ""
    last_time = ""
    row_count = 0
    with open(csv_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        indexes = {name.strip().lstrip("\ufeff"): idx for idx, name in enumerate(header)}
        time_idx = indexes.get("time")
        if time_idx is None:
            return first_time, last_time, row_count
        for row in reader:
            if time_idx >= len(row):
                continue
            current_time = row[time_idx].strip()
            if not current_time:
                continue
            if not first_time:
                first_time = current_time
            last_time = current_time
            row_count += 1
    return first_time, last_time, row_count


def _continuity_gap_seconds(first_time, last_time, row_count):
    if not first_time or not last_time or row_count <= 1:
        return 0
    try:
        elapsed = (_parse_time(last_time) - _parse_time(first_time)).total_seconds()
    except ValueError:
        return 0
    return int(elapsed - (row_count - 1))


def _rule_state_mismatch(row_state):
    bins = row_state["bins"]
    return len(set(bins.values())) > 1


def _rule_all_zero(row_state):
    return all(value == 0 for value in row_state["bins"].values())


MARKER_RULES = [
    {"event_type": "state_mismatch_over_5min", "predicate": _rule_state_mismatch},
    {"event_type": "all_zero_over_5min", "predicate": _rule_all_zero},
]


def _new_segment(event_type, row_state):
    return {
        "event_type": event_type,
        "start_row": row_state["row_index"],
        "end_row": row_state["row_index"],
        "start_time": row_state["time"],
        "end_time": row_state["time"],
        "last_row_index": row_state["row_index"],
    }


def _update_segment(segment, row_state):
    segment["end_row"] = row_state["row_index"]
    segment["end_time"] = row_state["time"]
    segment["last_row_index"] = row_state["row_index"]


def _flush_segment(segment, config, device_id, rows):
    if not segment:
        return
    duration_seconds = segment["end_row"] - segment["start_row"]
    if duration_seconds <= MIN_MARKER_SECONDS:
        return
    rows.append({
        "院区": config.LOCATION_CONFIG.get("name", config.LOCATION_CODE),
        "院区代码": config.LOCATION_CODE,
        "日期": config.FILE_DATE,
        "设备号": device_id,
        "事件类型": segment["event_type"],
        "开始行号": segment["start_row"],
        "结束行号": segment["end_row"],
        "持续秒数": duration_seconds,
        "持续分钟": round(duration_seconds / 60, 2),
        "开始时间": segment["start_time"],
        "结束时间": segment["end_time"],
    })


def _scan_timeline_file(config, device_id, csv_path):
    first_time, last_time, row_count = _read_first_last_times(csv_path)
    gap_seconds = _continuity_gap_seconds(first_time, last_time, row_count)
    if abs(gap_seconds) > MAX_CONTINUOUS_GAP_SECONDS:
        logging.warning(
            "timeline 可能不连续: %s | 首尾时间差与行数偏差 %s 秒",
            csv_path,
            gap_seconds,
        )

    markers = []
    active_segments = {rule["event_type"]: None for rule in MARKER_RULES}

    with open(csv_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        header = [cell.strip().lstrip("\ufeff") for cell in next(reader, [])]
        indexes = {name: idx for idx, name in enumerate(header)}
        missing = [column for column in REQUIRED_COLUMNS if column not in indexes]
        if missing:
            raise ValueError(f"timeline 缺少字段 {missing}: {csv_path}")

        row_index = 0
        for row in reader:
            row_index += 1
            time_text = _row_value(row, indexes, "time")
            if not time_text:
                continue
            raw = {column: _row_value(row, indexes, column, "0") for column in STATE_COLUMNS}
            bins = {column: _normalize_binary(raw[column]) for column in STATE_COLUMNS}
            row_state = {
                "row_index": row_index,
                "time": time_text,
                "raw": raw,
                "bins": bins,
            }

            for rule in MARKER_RULES:
                event_type = rule["event_type"]
                active = active_segments[event_type]
                matched = rule["predicate"](row_state)
                continuous = active is not None and row_index - active["last_row_index"] <= MAX_CONTINUOUS_GAP_SECONDS

                if matched and active is None:
                    active_segments[event_type] = _new_segment(event_type, row_state)
                elif matched and continuous:
                    _update_segment(active, row_state)
                elif matched:
                    _flush_segment(active, config, device_id, markers)
                    active_segments[event_type] = _new_segment(event_type, row_state)
                elif active is not None:
                    _flush_segment(active, config, device_id, markers)
                    active_segments[event_type] = None

    for event_type, active in active_segments.items():
        _flush_segment(active, config, device_id, markers)

    return markers


def run(config):
    logging.info("=== 开始生成 timeline marker 索引表 ===")
    output_dir = os.path.join(config.OUTPUT_DIR, OUTPUT_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, SUMMARY_FILENAME)
    rows = []
    scanned_files = 0

    for device_id, csv_path in _timeline_files(config) or []:
        scanned_files += 1
        try:
            rows.extend(_scan_timeline_file(config, device_id, csv_path))
        except Exception as e:
            logging.warning("timeline marker 跳过文件: %s | %s", csv_path, e)

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MARKER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    logging.info(
        "✅ timeline marker 索引完成：扫描 %s 个 timeline CSV，生成 %s 个 marker，输出 %s",
        scanned_files,
        len(rows),
        output_path,
    )
    return rows


def main():
    parser = argparse.ArgumentParser(description="生成轻量 timeline marker 索引表")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config.json 路径")
    parser.add_argument("--location", default="hf", help="院区代码，例如 hf")
    parser.add_argument("--date", required=True, help="目标日期，例如 2026-06-08；也可传 68")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    config_data = _load_config_data(args.config)
    target_date = _month_day_to_date(args.date)
    rows = run(_make_config(config_data, args.location, target_date))
    print({"markers": len(rows)})


if __name__ == "__main__":
    main()
