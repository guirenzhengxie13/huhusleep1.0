import argparse
import csv
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


OUTPUT_DIR_NAME = "inbed_flag_anomaly"
SUMMARY_FILENAME = "inbed_flag_anomaly_overview.csv"
STATUS_FILENAME = "_inbed_flag_anomaly_status.csv"
STATE_COLUMNS = ("move_state", "body_status", "inbed_flag")
REQUIRED_COLUMNS = ("time", *STATE_COLUMNS)
PLOT_LEVELS = {
    "move_state": (0.0, 0.90),
    "body_status": (0.05, 0.95),
    "inbed_flag": (0.10, 1.0),
}
SUMMARY_FIELDNAMES = [
    "院区",
    "院区代码",
    "日期",
    "设备号",
    "开始时间",
    "结束时间",
    "持续秒数",
    "持续分钟",
    "move_state众数",
    "body_status众数",
    "inbed_flag众数",
    "图片文件",
    "源文件",
]
STATUS_FIELDNAMES = [
    "源文件",
    "院区",
    "院区代码",
    "日期",
    "设备号",
    "文件大小",
    "修改时间",
    "检查状态",
    "检查时间",
    "异常段数",
    "输出目录",
    "错误",
]
MIN_ANOMALY_SECONDS = 60
MAX_CONTINUOUS_GAP_SECONDS = 10
PLOT_PADDING_SECONDS = 60
DEFAULT_CONFIG_PATH = "config.json"


plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _normalize_binary(value):
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0
    return 1 if numeric_value != 0 else 0


def _read_timeline(csv_path):
    header = pd.read_csv(csv_path, nrows=0)
    missing = [column for column in REQUIRED_COLUMNS if column not in header.columns]
    if missing:
        raise ValueError(f"timeline 缺少字段 {missing}: {csv_path}")

    df = pd.read_csv(csv_path, usecols=list(REQUIRED_COLUMNS))
    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    if df.empty:
        return df

    for column in STATE_COLUMNS:
        df[f"{column}_norm"] = df[column].apply(_normalize_binary).astype(int)

    df["mismatch"] = (
        (df["move_state_norm"] != df["body_status_norm"])
        | (df["body_status_norm"] != df["inbed_flag_norm"])
    )
    return df


def _iter_anomaly_segments(df):
    if df.empty:
        return

    time_gap = df["time"].diff().dt.total_seconds().fillna(0)
    new_block = (
        df["mismatch"].ne(df["mismatch"].shift(fill_value=False))
        | (time_gap > MAX_CONTINUOUS_GAP_SECONDS)
    )
    df = df.copy()
    df["block"] = new_block.cumsum()

    for _, segment in df[df["mismatch"]].groupby("block", sort=True):
        start_time = segment["time"].iloc[0]
        end_time = segment["time"].iloc[-1]
        duration_seconds = (end_time - start_time).total_seconds()
        if duration_seconds >= MIN_ANOMALY_SECONDS:
            yield segment, start_time, end_time, duration_seconds


def _time_axis_interval(start_time, end_time):
    total_minutes = max(1, (end_time - start_time).total_seconds() / 60)
    if total_minutes <= 10:
        return mdates.MinuteLocator(interval=1)
    if total_minutes <= 60:
        return mdates.MinuteLocator(interval=5)
    interval = max(10, math.ceil(total_minutes / 12))
    return mdates.MinuteLocator(interval=interval)


def _plot_anomaly(df, device_id, start_time, end_time, output_path):
    plot_start = start_time - timedelta(seconds=PLOT_PADDING_SECONDS)
    plot_end = end_time + timedelta(seconds=PLOT_PADDING_SECONDS)
    plot_df = df[(df["time"] >= plot_start) & (df["time"] <= plot_end)].copy()
    if plot_df.empty:
        return False

    fig, ax = plt.subplots(figsize=(14, 5))
    for column in STATE_COLUMNS:
        low_value, high_value = PLOT_LEVELS[column]
        y_values = plot_df[f"{column}_norm"].map({0: low_value, 1: high_value})
        ax.step(plot_df["time"], y_values, where="post", label=column, linewidth=2)
    ax.axvspan(start_time, end_time, color="#f6c344", alpha=0.25, label="异常时段")

    ax.set_title(f"{device_id} inbed_flag 状态不一致")
    ax.set_xlabel("时间")
    ax.set_ylabel("错位归一化状态")
    ax.set_ylim(-0.15, 1.15)
    ax.set_yticks([0, 0.05, 0.10, 0.90, 0.95, 1.0])
    ax.set_yticklabels(["move=0", "body=0", "inbed=0", "move=1", "body=1", "inbed=1"])
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper right")
    ax.xaxis.set_major_locator(_time_axis_interval(plot_start, plot_end))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


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


def _mode_text(segment, column):
    values = segment[column].dropna()
    if values.empty:
        return ""
    modes = values.mode(dropna=True)
    if modes.empty:
        return ""
    return str(modes.iloc[0])


def _summary_row(config, device_id, csv_path, segment, start_time, end_time, duration_seconds, plot_path):
    return {
        "院区": config.LOCATION_CONFIG.get("name", config.LOCATION_CODE),
        "院区代码": config.LOCATION_CODE,
        "日期": config.FILE_DATE,
        "设备号": device_id,
        "开始时间": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "结束时间": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "持续秒数": int(duration_seconds),
        "持续分钟": round(duration_seconds / 60, 2),
        "move_state众数": _mode_text(segment, "move_state"),
        "body_status众数": _mode_text(segment, "body_status"),
        "inbed_flag众数": _mode_text(segment, "inbed_flag"),
        "图片文件": os.path.basename(plot_path),
        "源文件": os.path.abspath(csv_path),
    }


def _analyze_timeline_file(config, device_id, csv_path):
    output_dir = os.path.join(config.OUTPUT_DIR, OUTPUT_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)
    rows = []
    df = _read_timeline(csv_path)
    if df.empty:
        return rows

    for segment, start_time, end_time, duration_seconds in _iter_anomaly_segments(df):
        start_key = start_time.strftime("%Y%m%d_%H%M%S")
        end_key = end_time.strftime("%H%M%S")
        plot_filename = f"{device_id}_{start_key}_{end_key}.png"
        plot_path = os.path.join(output_dir, plot_filename)
        if _plot_anomaly(df, device_id, start_time, end_time, plot_path):
            rows.append(_summary_row(config, device_id, csv_path, segment, start_time, end_time, duration_seconds, plot_path))
    return rows


def _write_summary(summary_path, rows):
    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def run(config):
    logging.info("=== 开始检测 inbed_flag 状态异常 ===")

    output_dir = os.path.join(config.OUTPUT_DIR, OUTPUT_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, SUMMARY_FILENAME)
    rows = []
    checked_devices = 0

    for device_id, csv_path in _timeline_files(config) or []:
        checked_devices += 1
        try:
            rows.extend(_analyze_timeline_file(config, device_id, csv_path))
        except Exception as e:
            logging.warning("inbed_flag 异常检测跳过设备 %s: %s", device_id, e)

    _write_summary(summary_path, rows)

    logging.info(
        "✅ inbed_flag 异常检测完成：检查设备 %s 台，发现异常时段 %s 段，输出 %s",
        checked_devices,
        len(rows),
        output_dir,
    )
    return rows


def _load_config_data(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _common_data_root(config_data):
    base_paths = [
        str(location_config.get("base_data_path", "")).rstrip("\\/")
        for location_config in config_data.values()
        if location_config.get("base_data_path")
    ]
    if not base_paths:
        return os.path.join(os.path.expanduser("~"), "Desktop", "data")
    try:
        return os.path.commonpath(base_paths)
    except ValueError:
        return os.path.dirname(base_paths[0])


def _read_status(status_path):
    if not os.path.exists(status_path):
        return {}
    with open(status_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return {row.get("源文件", ""): row for row in reader if row.get("源文件")}


def _write_status(status_path, status_by_path):
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    with open(status_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STATUS_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for source_path in sorted(status_by_path):
            writer.writerow(status_by_path[source_path])


def _file_signature(csv_path):
    stat = os.stat(csv_path)
    return str(stat.st_size), str(int(stat.st_mtime))


def _already_done(status_row, csv_path):
    if not status_row or status_row.get("检查状态") != "done":
        return False
    file_size, mtime = _file_signature(csv_path)
    return status_row.get("文件大小") == file_size and status_row.get("修改时间") == mtime


def _append_summary_rows(summary_path, source_path, new_rows):
    existing_rows = []
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("源文件") != os.path.abspath(source_path):
                    existing_rows.append(row)
    _write_summary(summary_path, existing_rows + new_rows)


def _date_from_timeline_filename(filename, month_day_folder):
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", filename)
    if match:
        return match.group(1)
    match = re.search(r"(20\d{6})", filename)
    if match:
        value = match.group(1)
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    year = datetime.now().year
    match = re.fullmatch(r"(\d{1,2})(\d{1,2})", month_day_folder)
    if match:
        return f"{year}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return datetime.now().strftime("%Y-%m-%d")


def _standalone_configs(config_data):
    for location_code, location_config in sorted(config_data.items()):
        base_data_path = location_config.get("base_data_path")
        if not base_data_path:
            continue
        timeline_root = os.path.join(base_data_path, "timeline")
        if not os.path.exists(timeline_root):
            continue

        for month_day_folder in sorted(os.listdir(timeline_root)):
            timeline_dir = os.path.join(timeline_root, month_day_folder)
            if not os.path.isdir(timeline_dir):
                continue
            output_dir = os.path.join(base_data_path, "output", month_day_folder)
            for device_id in sorted(os.listdir(timeline_dir)):
                device_dir = os.path.join(timeline_dir, device_id)
                if not os.path.isdir(device_dir):
                    continue
                for filename in sorted(os.listdir(device_dir)):
                    if not filename.lower().endswith(".csv"):
                        continue
                    csv_path = os.path.abspath(os.path.join(device_dir, filename))
                    target_date = _date_from_timeline_filename(filename, month_day_folder)
                    config = type("InbedFlagStandaloneConfig", (), {})()
                    config.LOCATION_CONFIG = location_config
                    config.LOCATION_CODE = location_code
                    config.FILE_DATE = target_date
                    config.TIMELINE_DIR = timeline_dir
                    config.OUTPUT_DIR = output_dir
                    yield config, device_id, csv_path


def run_all_local_timelines(config_path=DEFAULT_CONFIG_PATH, status_path=None, force=False):
    config_data = _load_config_data(config_path)
    data_root = _common_data_root(config_data)
    status_path = status_path or os.path.join(data_root, STATUS_FILENAME)
    status_by_path = _read_status(status_path)

    processed = skipped = failed = anomaly_count = 0

    for config, device_id, csv_path in _standalone_configs(config_data):
        source_path = os.path.abspath(csv_path)
        file_size, mtime = _file_signature(source_path)
        output_dir = os.path.join(config.OUTPUT_DIR, OUTPUT_DIR_NAME)
        summary_path = os.path.join(output_dir, SUMMARY_FILENAME)

        if not force and _already_done(status_by_path.get(source_path), source_path):
            skipped += 1
            continue

        checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            rows = _analyze_timeline_file(config, device_id, source_path)
            _append_summary_rows(summary_path, source_path, rows)
            status_by_path[source_path] = {
                "源文件": source_path,
                "院区": config.LOCATION_CONFIG.get("name", config.LOCATION_CODE),
                "院区代码": config.LOCATION_CODE,
                "日期": config.FILE_DATE,
                "设备号": device_id,
                "文件大小": file_size,
                "修改时间": mtime,
                "检查状态": "done",
                "检查时间": checked_at,
                "异常段数": str(len(rows)),
                "输出目录": output_dir,
                "错误": "",
            }
            processed += 1
            anomaly_count += len(rows)
        except Exception as e:
            status_by_path[source_path] = {
                "源文件": source_path,
                "院区": config.LOCATION_CONFIG.get("name", config.LOCATION_CODE),
                "院区代码": config.LOCATION_CODE,
                "日期": config.FILE_DATE,
                "设备号": device_id,
                "文件大小": file_size,
                "修改时间": mtime,
                "检查状态": "failed",
                "检查时间": checked_at,
                "异常段数": "0",
                "输出目录": output_dir,
                "错误": str(e),
            }
            failed += 1
            logging.warning("inbed_flag 全量检测失败: %s | %s", source_path, e)

        if (processed + failed) % 50 == 0:
            _write_status(status_path, status_by_path)
            logging.info("全量检测进度：处理 %s，跳过 %s，失败 %s", processed, skipped, failed)

    _write_status(status_path, status_by_path)
    logging.info(
        "✅ 本地 timeline 全量检测完成：处理 %s，跳过已处理 %s，失败 %s，新增异常 %s，状态表 %s",
        processed,
        skipped,
        failed,
        anomaly_count,
        status_path,
    )
    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "anomaly_count": anomaly_count,
        "status_path": status_path,
    }


def main():
    parser = argparse.ArgumentParser(description="独立检测本地所有 timeline 的 inbed_flag 状态异常")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config.json 路径")
    parser.add_argument("--status-path", default=None, help="检查状态 CSV 路径，默认写到数据根目录")
    parser.add_argument("--force", action="store_true", help="忽略状态表，重新检查所有 timeline CSV")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    result = run_all_local_timelines(config_path=args.config, status_path=args.status_path, force=args.force)
    print(result)


if __name__ == "__main__":
    main()
