import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils import clean_name, get_device_mapping


DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
DEFAULT_LOCATION_CODE = "hf"
DEFAULT_TARGET_DATE = "2026-06-07"
DEFAULT_OUTPUT_DIR_NAME = "sleep_report_leave_alert_overlay"
DEFAULT_ROSTER_PATH = os.path.join(PROJECT_ROOT, "assets", "full_device_roster.csv")

PLOT_LEVELS = {
    "move_state": (0.0, 0.90),
    "body_status": (0.05, 0.95),
    "inbed_flag": (0.10, 1.0),
}
STATE_COLUMNS = ("move_state", "body_status", "inbed_flag")
REQUIRED_COLUMNS = ("time", *STATE_COLUMNS)
WINDOW_BEFORE_MINUTES = 5
WINDOW_AFTER_MINUTES = 15
MIN_MISMATCH_SECONDS = 5 * 60
MAX_CONTINUOUS_GAP_SECONDS = 10
SUMMARY_FILENAME = "sleep_report_leave_alert_overlay_summary.csv"


plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _load_config_data(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _month_day_folder(target_date):
    text = str(target_date).strip()
    if re.fullmatch(r"\d{1,4}", text):
        return f"{int(text)}"
    dt = datetime.strptime(text, "%Y-%m-%d")
    return f"{dt.month}{dt.day}"


def _default_paths(config_path, location_code, target_date, output_dir_name=DEFAULT_OUTPUT_DIR_NAME):
    config_data = _load_config_data(config_path)
    if location_code not in config_data:
        raise KeyError(f"config.json 中找不到院区配置: {location_code}")

    base_data_path = config_data[location_code]["base_data_path"]
    month_day = _month_day_folder(target_date)
    output_root = os.path.join(base_data_path, "output", month_day)
    return {
        "sleep_report_path": os.path.join(output_root, "sleep_report", "睡眠报告.txt"),
        "warn_dir": os.path.join(base_data_path, "warn", month_day),
        "timeline_dir": os.path.join(base_data_path, "timeline", month_day),
        "output_dir": os.path.join(output_root, output_dir_name),
        "marker_path": os.path.join(output_root, "timeline_markers", "timeline_markers.csv"),
        "roster_path": os.path.join(PROJECT_ROOT, "assets", config_data[location_code].get("device_roster_name", "full_device_roster.csv")),
    }


def _parse_year_from_warn_dir(warn_dir):
    for filename in sorted(os.listdir(warn_dir)) if os.path.exists(warn_dir) else []:
        match = re.search(r"(20\d{2})\d{4}", filename)
        if match:
            return int(match.group(1))
    return datetime.now().year


def _parse_month_day_time(value, year):
    value = value.strip()
    return datetime.strptime(f"{year}-{value}", "%Y-%m-%d %H:%M:%S")


def _parse_sleep_report_events(sleep_report_path, device_map, year):
    events = []
    pattern = re.compile(r"^(?P<name>[^|]+)\|(?P<room>[^|]+)\|.*?离床时间：(?P<leave_times>.*)$")
    with open(sleep_report_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("=") or line.startswith("今日有部分设备"):
                continue
            match = pattern.match(line.replace(" | ", "|"))
            if not match:
                continue

            name = clean_name(match.group("name"))
            device_id = device_map.get(name)
            if not device_id:
                logging.warning("睡眠报告老人未匹配设备号，跳过: %s", name)
                continue

            leave_text = match.group("leave_times").strip()
            if not leave_text:
                continue

            for item in re.split(r"[、,，]\s*", leave_text):
                item = item.strip()
                if not item:
                    continue
                try:
                    leave_time = _parse_month_day_time(item, year)
                except ValueError:
                    logging.warning("无法解析睡眠报告离床时间: %s | %s", name, item)
                    continue
                events.append({
                    "name": name,
                    "room": match.group("room").strip(),
                    "device_id": device_id,
                    "leave_time": leave_time,
                })
    events.sort(key=lambda item: (item["leave_time"], item["device_id"]))
    return events


def _read_alerts_by_name(warn_dir):
    alerts = defaultdict(list)
    if not os.path.exists(warn_dir):
        return alerts

    for filename in sorted(os.listdir(warn_dir)):
        if not filename.lower().endswith(".csv"):
            continue
        warn_path = os.path.join(warn_dir, filename)
        with open(warn_path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                alert_name = (row.get("告警名称") or "").strip()
                if "离床" not in alert_name:
                    continue
                name = clean_name(row.get("姓名"))
                try:
                    alert_time = datetime.strptime((row.get("告警时间") or "").strip(), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                alerts[name].append({
                    "alert_name": alert_name,
                    "alert_time": alert_time,
                    "source_file": warn_path,
                })

    for values in alerts.values():
        values.sort(key=lambda item: item["alert_time"])
    return alerts


def _nearest_alert(alerts, target_time, window_start, window_end):
    window_alerts = [
        alert for alert in alerts
        if window_start <= alert["alert_time"] <= window_end
    ]
    if not window_alerts:
        return None
    return min(window_alerts, key=lambda item: abs((item["alert_time"] - target_time).total_seconds()))


def _normalize_binary(value):
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0
    return 1 if numeric_value != 0 else 0


def _read_timeline_window(timeline_dir, device_id, start_time, end_time):
    device_dir = os.path.join(timeline_dir, device_id)
    if not os.path.exists(device_dir):
        raise FileNotFoundError(f"未找到设备 timeline 目录: {device_dir}")

    frames = []
    for filename in sorted(os.listdir(device_dir)):
        if not filename.lower().endswith(".csv"):
            continue
        csv_path = os.path.join(device_dir, filename)
        header = pd.read_csv(csv_path, nrows=0)
        missing = [column for column in REQUIRED_COLUMNS if column not in header.columns]
        if missing:
            continue
        df = pd.read_csv(csv_path, usecols=list(REQUIRED_COLUMNS))
        if df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])
        df = df[(df["time"] >= start_time) & (df["time"] <= end_time)]
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    df = pd.concat(frames, ignore_index=True).sort_values("time").reset_index(drop=True)
    for column in STATE_COLUMNS:
        df[f"{column}_norm"] = df[column].apply(_normalize_binary).astype(int)
    df["mismatch"] = (
        (df["move_state_norm"] != df["body_status_norm"])
        | (df["body_status_norm"] != df["inbed_flag_norm"])
    )
    return df


def _plot_y_values(df, column):
    low_value, high_value = PLOT_LEVELS[column]
    return df[f"{column}_norm"].map({0: low_value, 1: high_value})


def _annotate_time(ax, event_time, label, color, y, x_min, x_max):
    if event_time < x_min or event_time > x_max:
        return False
    ax.axvline(event_time, color=color, linestyle="--", linewidth=1.8)
    ax.annotate(
        label,
        xy=(event_time, y),
        xytext=(event_time, y + 0.18),
        arrowprops=dict(arrowstyle="->", color=color, lw=1.5),
        color=color,
        fontsize=10,
        ha="center",
        va="bottom",
    )
    return True


def _iter_mismatch_segments(df):
    if df.empty or "mismatch" not in df.columns:
        return

    time_gap = df["time"].diff().dt.total_seconds().fillna(0)
    new_block = (
        df["mismatch"].ne(df["mismatch"].shift(fill_value=False))
        | (time_gap > MAX_CONTINUOUS_GAP_SECONDS)
    )
    work_df = df.copy()
    work_df["block"] = new_block.cumsum()
    for _, segment in work_df[work_df["mismatch"]].groupby("block", sort=True):
        start_time = segment["time"].iloc[0]
        end_time = segment["time"].iloc[-1]
        duration_seconds = (end_time - start_time).total_seconds()
        if duration_seconds > MIN_MISMATCH_SECONDS:
            yield start_time, end_time, duration_seconds


def _load_marker_segments(marker_path):
    segments_by_device = defaultdict(list)
    if not marker_path or not os.path.exists(marker_path):
        return segments_by_device

    with open(marker_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("事件类型") or "").strip() != "state_mismatch_over_5min":
                continue
            device_id = (row.get("设备号") or "").strip()
            if not device_id:
                continue
            try:
                start_time = datetime.strptime((row.get("开始时间") or "").strip(), "%Y-%m-%d %H:%M:%S")
                end_time = datetime.strptime((row.get("结束时间") or "").strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            duration_seconds = (end_time - start_time).total_seconds()
            segments_by_device[device_id].append((start_time, end_time, duration_seconds))

    for values in segments_by_device.values():
        values.sort(key=lambda item: item[0])
    return segments_by_device


def _marker_segments_in_window(segments, window_start, window_end):
    return [
        (start_time, end_time, duration_seconds)
        for start_time, end_time, duration_seconds in segments
        if start_time <= window_end and end_time >= window_start
    ]


def _plot_event(event, nearest_alert, df, output_path, window_start, window_end, mismatch_segments=None):
    fig, ax = plt.subplots(figsize=(14, 5))
    if mismatch_segments is None:
        mismatch_segments = list(_iter_mismatch_segments(df)) if not df.empty else []

    if not df.empty:
        for column in STATE_COLUMNS:
            ax.step(df["time"], _plot_y_values(df, column), where="post", label=column, linewidth=2)
    else:
        ax.text(0.5, 0.5, "窗口内无 timeline 数据", transform=ax.transAxes, ha="center", va="center", fontsize=14)

    leave_time = event["leave_time"]
    _annotate_time(ax, leave_time, "睡眠报告离床", "#d62728", 0.72, window_start, window_end)

    for index, (mismatch_start, mismatch_end, duration_seconds) in enumerate(mismatch_segments):
        ax.axvspan(
            mismatch_start,
            mismatch_end,
            color="#f6c344",
            alpha=0.25,
            label="三值不匹配>5分钟" if index == 0 else None,
        )
        midpoint = mismatch_start + (mismatch_end - mismatch_start) / 2
        if window_start <= midpoint <= window_end:
            ax.text(
                midpoint,
                1.16,
                f"不匹配 {duration_seconds / 60:.1f} 分钟",
                ha="center",
                va="center",
                fontsize=9,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#d6a500", alpha=0.85),
            )

    status = "无离床预警"
    delta_seconds = ""
    alert_time_text = ""
    if nearest_alert:
        alert_time = nearest_alert["alert_time"]
        delta = (alert_time - leave_time).total_seconds()
        delta_seconds = int(delta)
        alert_time_text = alert_time.strftime("%Y-%m-%d %H:%M:%S")
        status = "有离床预警"
        if _annotate_time(ax, alert_time, "最近离床预警", "#2ca02c", 0.42, window_start, window_end):
            midpoint = leave_time + (alert_time - leave_time) / 2
            if window_start <= midpoint <= window_end:
                ax.annotate(
                    f"Δ {delta / 60:.1f} 分钟",
                    xy=(midpoint, 1.08),
                    xytext=(midpoint, 1.08),
                    color="#111111",
                    fontsize=11,
                    ha="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#999999", alpha=0.85),
                )
        else:
            ax.text(
                0.01,
                0.96,
                f"最近预警不在绘图窗口内，Δ {delta / 60:.1f} 分钟",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=10,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#999999", alpha=0.85),
            )
    else:
        ax.text(
            0.01,
            0.96,
            "无离床预警：正常",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#999999", alpha=0.85),
        )

    ax.set_title(f"{event['name']} {event['device_id']} 睡眠报告离床点核对")
    ax.set_xlim(window_start, window_end)
    ax.set_ylim(-0.15, 1.25)
    ax.set_yticks([0, 0.05, 0.10, 0.90, 0.95, 1.0])
    ax.set_yticklabels(["move=0", "body=0", "inbed=0", "move=1", "body=1", "inbed=1"])
    ax.set_xlabel("时间")
    ax.set_ylabel("错位归一化状态")
    ax.grid(True, linestyle="--", alpha=0.35)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="lower right")
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return status, alert_time_text, delta_seconds, mismatch_segments


def _safe_filename(value):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value)


def run(
    sleep_report_path,
    warn_dir,
    timeline_dir,
    output_dir,
    roster_path=DEFAULT_ROSTER_PATH,
    marker_path=None,
):
    os.makedirs(output_dir, exist_ok=True)
    year = _parse_year_from_warn_dir(warn_dir)
    device_map = get_device_mapping(roster_path)
    events = _parse_sleep_report_events(sleep_report_path, device_map, year)
    alerts_by_name = _read_alerts_by_name(warn_dir)
    marker_segments_by_device = _load_marker_segments(marker_path)
    summary_rows = []

    for event in events:
        leave_time = event["leave_time"]
        window_start = leave_time - timedelta(minutes=WINDOW_BEFORE_MINUTES)
        window_end = leave_time + timedelta(minutes=WINDOW_AFTER_MINUTES)
        nearest_alert = _nearest_alert(alerts_by_name.get(event["name"], []), leave_time, window_start, window_end)
        base_filename = (
            f"{event['device_id']}_{_safe_filename(event['name'])}_"
            f"{leave_time.strftime('%Y%m%d_%H%M%S')}.png"
        )
        output_path = os.path.join(output_dir, base_filename)

        try:
            df = _read_timeline_window(timeline_dir, event["device_id"], window_start, window_end)
            marker_mismatch_segments = None
            if marker_segments_by_device:
                marker_mismatch_segments = _marker_segments_in_window(
                    marker_segments_by_device.get(event["device_id"], []),
                    window_start,
                    window_end,
                )
            status, alert_time_text, delta_seconds, mismatch_segments = _plot_event(
                event,
                nearest_alert,
                df,
                output_path,
                window_start,
                window_end,
                marker_mismatch_segments,
            )
            filename = base_filename
            if mismatch_segments:
                filename = f"error_{base_filename}"
                error_output_path = os.path.join(output_dir, filename)
                if os.path.exists(error_output_path):
                    os.remove(error_output_path)
                os.replace(output_path, error_output_path)
            summary_rows.append({
                "姓名": event["name"],
                "房间床位": event["room"],
                "设备号": event["device_id"],
                "睡眠报告离床时间": leave_time.strftime("%Y-%m-%d %H:%M:%S"),
                "最近离床预警时间": alert_time_text,
                "预警-离床差值秒": delta_seconds,
                "预警-离床差值分钟": round(delta_seconds / 60, 2) if delta_seconds != "" else "",
                "状态": status,
                "三值不匹配>5分钟": "是" if mismatch_segments else "否",
                "不匹配区间数": len(mismatch_segments),
                "图片文件": filename,
            })
        except Exception as e:
            logging.warning("绘制失败: %s %s | %s", event["device_id"], leave_time, e)
            summary_rows.append({
                "姓名": event["name"],
                "房间床位": event["room"],
                "设备号": event["device_id"],
                "睡眠报告离床时间": leave_time.strftime("%Y-%m-%d %H:%M:%S"),
                "最近离床预警时间": "",
                "预警-离床差值秒": "",
                "预警-离床差值分钟": "",
                "状态": f"绘制失败: {e}",
                "三值不匹配>5分钟": "",
                "不匹配区间数": "",
                "图片文件": "",
            })

    summary_path = os.path.join(output_dir, "sleep_report_leave_alert_overlay_summary.csv")
    fieldnames = ["姓名", "房间床位", "设备号", "睡眠报告离床时间", "最近离床预警时间", "预警-离床差值秒", "预警-离床差值分钟", "状态", "三值不匹配>5分钟", "不匹配区间数", "图片文件"]
    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    logging.info("完成：离床点 %s 个，输出 %s", len(summary_rows), output_dir)
    return summary_rows


def main():
    parser = argparse.ArgumentParser(description="合肥睡眠报告离床点与最近离床预警叠加图")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config.json 路径")
    parser.add_argument("--location", default=DEFAULT_LOCATION_CODE, help="院区代码，例如 hf")
    parser.add_argument("--date", default=DEFAULT_TARGET_DATE, help="任务日期，例如 2026-06-07；也可传 67")
    parser.add_argument("--output-dir-name", default=DEFAULT_OUTPUT_DIR_NAME, help="output/<月日> 下的输出文件夹名")
    parser.add_argument("--sleep-report", default=None)
    parser.add_argument("--warn-dir", default=None)
    parser.add_argument("--timeline-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--roster", default=None)
    parser.add_argument("--marker-csv", default=None, help="timeline_markers.csv 路径；传入后直接用 marker 标注不匹配背景")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    paths = _default_paths(args.config, args.location, args.date, args.output_dir_name)
    sleep_report_path = args.sleep_report or paths["sleep_report_path"]
    warn_dir = args.warn_dir or paths["warn_dir"]
    timeline_dir = args.timeline_dir or paths["timeline_dir"]
    output_dir = args.output_dir or paths["output_dir"]
    roster_path = args.roster or paths["roster_path"]
    marker_path = args.marker_csv or (paths["marker_path"] if os.path.exists(paths["marker_path"]) else None)
    rows = run(sleep_report_path, warn_dir, timeline_dir, output_dir, roster_path, marker_path)
    print({"events": len(rows), "output_dir": output_dir})


if __name__ == "__main__":
    main()
