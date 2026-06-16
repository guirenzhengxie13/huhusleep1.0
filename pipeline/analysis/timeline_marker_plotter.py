import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from pipeline.analysis import hefei_sleep_report_leave_alert_overlay as overlay_plot
from pipeline.analysis import timeline_marker


DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
OUTPUT_DIR_NAME = "timeline_marker_plots"
SUMMARY_FILENAME = "timeline_marker_plot_summary.csv"
STATE_COLUMNS = overlay_plot.STATE_COLUMNS
REQUIRED_COLUMNS = overlay_plot.REQUIRED_COLUMNS
PLOT_LEVELS = overlay_plot.PLOT_LEVELS
DEFAULT_PADDING_SECONDS = 60


plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _load_config_data(config_path=DEFAULT_CONFIG_PATH):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_config(config_data, location_code, target_date):
    location_config = dict(config_data[location_code])
    location_config["code"] = location_code
    return Config(location_config, target_date)


def _normalize_binary(value):
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0
    return 1 if numeric_value != 0 else 0


def _row_value(row, indexes, column, default=""):
    index = indexes.get(column)
    if index is None or index >= len(row):
        return default
    return str(row[index]).strip()


def _parse_time(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _safe_filename(value):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(value)).strip("_")


def _marker_value(row, *names):
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def _read_markers(marker_path, event_types=None, device_ids=None):
    event_type_filter = set(event_types or [])
    device_filter = set(device_ids or [])
    with open(marker_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            device_id = _marker_value(row, "设备号")
            event_type = _marker_value(row, "事件类型")
            if event_type_filter and event_type not in event_type_filter:
                continue
            if device_filter and device_id not in device_filter:
                continue
            yield row


def _timeline_csv_candidates(timeline_dir, device_id):
    device_dir = os.path.join(timeline_dir, device_id)
    if not os.path.isdir(device_dir):
        return []
    return [
        os.path.join(device_dir, filename)
        for filename in sorted(os.listdir(device_dir))
        if filename.lower().endswith(".csv")
    ]


def _resolve_timeline_csv(timeline_dir, device_id, marker_start_time):
    candidates = _timeline_csv_candidates(timeline_dir, device_id)
    if not candidates:
        raise FileNotFoundError(f"未找到设备 timeline 目录或 CSV: {device_id}")
    if len(candidates) == 1:
        return candidates[0]

    marker_time = _parse_time(marker_start_time)
    fallback = candidates[0]
    for csv_path in candidates:
        first_time, last_time, row_count = timeline_marker._read_first_last_times(csv_path)
        if not first_time or not last_time or row_count <= 0:
            continue
        try:
            if _parse_time(first_time) <= marker_time <= _parse_time(last_time):
                return csv_path
        except ValueError:
            continue
    return fallback


def _read_timeline_rows(csv_path, start_row, end_row, padding_seconds=DEFAULT_PADDING_SECONDS):
    read_start = max(1, int(start_row) - int(padding_seconds))
    read_end = int(end_row) + int(padding_seconds)
    rows = []

    with open(csv_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        header = [cell.strip().lstrip("\ufeff") for cell in next(reader, [])]
        indexes = {name: idx for idx, name in enumerate(header)}
        missing = [column for column in REQUIRED_COLUMNS if column not in indexes]
        if missing:
            raise ValueError(f"timeline 缺少字段 {missing}: {csv_path}")

        for row_index, row in enumerate(reader, start=1):
            if row_index < read_start:
                continue
            if row_index > read_end:
                break
            rows.append({column: _row_value(row, indexes, column, "0") for column in REQUIRED_COLUMNS})

    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    for column in STATE_COLUMNS:
        df[f"{column}_norm"] = df[column].apply(_normalize_binary).astype(int)
    df["mismatch"] = (
        (df["move_state_norm"] != df["body_status_norm"])
        | (df["body_status_norm"] != df["inbed_flag_norm"])
    )
    df["all_zero"] = (
        (df["move_state_norm"] == 0)
        & (df["body_status_norm"] == 0)
        & (df["inbed_flag_norm"] == 0)
    )
    return df


def _plot_y_values(df, column):
    low_value, high_value = PLOT_LEVELS[column]
    return df[f"{column}_norm"].map({0: low_value, 1: high_value})


def _plot_marker(marker, df, output_path):
    event_type = _marker_value(marker, "事件类型")
    device_id = _marker_value(marker, "设备号")
    start_time = pd.to_datetime(_marker_value(marker, "开始时间"))
    end_time = pd.to_datetime(_marker_value(marker, "结束时间"))
    duration_minutes = _marker_value(marker, "持续分钟")

    fig, ax = plt.subplots(figsize=(14, 5))
    if not df.empty:
        for column in STATE_COLUMNS:
            ax.step(df["time"], _plot_y_values(df, column), where="post", label=column, linewidth=2)
    else:
        ax.text(0.5, 0.5, "窗口内无 timeline 数据", transform=ax.transAxes, ha="center", va="center", fontsize=14)

    if event_type == "state_mismatch_over_5min":
        color = "#f6c344"
        label = "三值不匹配 > 5分钟"
    elif event_type == "all_zero_over_5min":
        color = "#b7b7b7"
        label = "三值全 0 > 5分钟"
    else:
        color = "#9ecae1"
        label = event_type

    ax.axvspan(start_time, end_time, color=color, alpha=0.28, label=label)
    midpoint = start_time + (end_time - start_time) / 2
    ax.text(
        midpoint,
        1.16,
        f"{duration_minutes} 分钟",
        ha="center",
        va="center",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, alpha=0.88),
    )

    if not df.empty:
        ax.set_xlim(df["time"].min(), df["time"].max())
    else:
        ax.set_xlim(start_time, end_time)
    ax.set_ylim(-0.15, 1.25)
    ax.set_yticks([0, 0.05, 0.10, 0.90, 0.95, 1.0])
    ax.set_yticklabels(["move=0", "body=0", "inbed=0", "move=1", "body=1", "inbed=1"])
    ax.set_title(f"{device_id} {event_type} {start_time:%Y-%m-%d %H:%M:%S} - {end_time:%H:%M:%S}")
    ax.set_xlabel("时间")
    ax.set_ylabel("错位归一化状态")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="lower right")
    locator = mdates.AutoDateLocator(minticks=5, maxticks=12)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.autofmt_xdate(rotation=25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_filename(marker):
    event_type = _marker_value(marker, "事件类型")
    device_id = _marker_value(marker, "设备号")
    start_time = _parse_time(_marker_value(marker, "开始时间"))
    end_time = _parse_time(_marker_value(marker, "结束时间"))
    prefix = "error" if event_type == "state_mismatch_over_5min" else _safe_filename(event_type)
    return f"{prefix}_{device_id}_{start_time:%Y%m%d_%H%M%S}_{end_time:%H%M%S}.png"


def run(
    config,
    marker_path=None,
    output_dir=None,
    event_types=None,
    device_ids=None,
    limit=None,
    padding_seconds=DEFAULT_PADDING_SECONDS,
):
    marker_path = marker_path or os.path.join(config.OUTPUT_DIR, timeline_marker.OUTPUT_DIR_NAME, timeline_marker.SUMMARY_FILENAME)
    output_dir = output_dir or os.path.join(config.OUTPUT_DIR, OUTPUT_DIR_NAME)
    os.makedirs(output_dir, exist_ok=True)

    summary_rows = []
    plotted = 0
    for marker in _read_markers(marker_path, event_types=event_types, device_ids=device_ids):
        if limit is not None and plotted >= limit:
            break
        device_id = _marker_value(marker, "设备号")
        start_row = int(_marker_value(marker, "开始行号"))
        end_row = int(_marker_value(marker, "结束行号"))
        try:
            csv_path = _resolve_timeline_csv(config.TIMELINE_DIR, device_id, _marker_value(marker, "开始时间"))
            df = _read_timeline_rows(csv_path, start_row, end_row, padding_seconds=padding_seconds)
            filename = _plot_filename(marker)
            _plot_marker(marker, df, os.path.join(output_dir, filename))
            summary_rows.append({**marker, "图片文件": filename})
            plotted += 1
        except Exception as e:
            logging.warning("timeline marker 画图跳过: %s | %s", marker, e)
            summary_rows.append({**marker, "图片文件": "", "错误": str(e)})

    summary_path = os.path.join(output_dir, SUMMARY_FILENAME)
    fieldnames = list(timeline_marker.MARKER_FIELDNAMES) + ["图片文件"]
    if any("错误" in row for row in summary_rows):
        fieldnames.append("错误")
    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary_rows)

    logging.info("timeline marker 画图完成：%s 张，输出 %s", plotted, output_dir)
    return summary_rows


def main():
    parser = argparse.ArgumentParser(description="根据 timeline marker 索引回读 timeline 局部数据并画图")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config.json 路径")
    parser.add_argument("--location", default="hf", help="院区代码，例如 hf")
    parser.add_argument("--date", required=True, help="目标日期，例如 2026-06-08；也可传 68")
    parser.add_argument("--marker-csv", default=None, help="timeline_markers.csv 路径")
    parser.add_argument("--output-dir", default=None, help="图片输出目录")
    parser.add_argument("--event-type", action="append", default=None, help="只画指定事件类型，可重复传")
    parser.add_argument("--devices", default="", help="只画指定设备号，多个用逗号分隔")
    parser.add_argument("--limit", type=int, default=None, help="最多画多少张，调试用")
    parser.add_argument("--padding-seconds", type=int, default=DEFAULT_PADDING_SECONDS, help="事件前后额外回读秒数")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    config_data = _load_config_data(args.config)
    target_date = timeline_marker._month_day_to_date(args.date)
    config = _make_config(config_data, args.location, target_date)
    devices = [item.strip() for item in args.devices.split(",") if item.strip()]
    rows = run(
        config,
        marker_path=args.marker_csv,
        output_dir=args.output_dir,
        event_types=args.event_type,
        device_ids=devices,
        limit=args.limit,
        padding_seconds=args.padding_seconds,
    )
    print({"plots": sum(1 for row in rows if row.get("图片文件")), "rows": len(rows)})


if __name__ == "__main__":
    main()
