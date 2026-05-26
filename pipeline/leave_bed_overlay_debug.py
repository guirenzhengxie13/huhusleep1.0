import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from utils import clean_name, get_device_mapping


plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False

DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
INBED_FLAG_COLUMNS = ("inbed_flag", "inbedflag", "inbedFlag")
WARN_REQUIRED_COLUMNS = {"姓名", "告警名称", "告警时间"}


def _parse_date(value):
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"日期格式错误: {value}，请使用 2026-05-08 或 20260508")


def _load_config_data(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_config(config_data, location_code, target_date):
    location_config = dict(config_data[location_code])
    location_config["code"] = location_code
    return Config(location_config, target_date)


def _normalize_state(value):
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0
    return int(numeric_value)


def _find_inbed_column(columns):
    for column in INBED_FLAG_COLUMNS:
        if column in columns:
            return column
    return None


def _read_warning_rows(config, alert_keyword):
    warn_files = [
        os.path.join(config.WARN_DIR, filename)
        for filename in os.listdir(config.WARN_DIR)
        if filename.endswith(".csv")
    ] if os.path.exists(config.WARN_DIR) else []

    rows = []
    for warn_file in warn_files:
        try:
            df = pd.read_csv(warn_file, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(warn_file, encoding="utf-8")

        if not WARN_REQUIRED_COLUMNS.issubset(df.columns):
            logging.warning("告警 CSV 字段不完整，跳过: %s", warn_file)
            continue

        if alert_keyword:
            df = df[df["告警名称"].astype(str).str.contains(alert_keyword, na=False)]

        for _, row in df.iterrows():
            try:
                alert_time = pd.to_datetime(row["告警时间"]).to_pydatetime()
            except Exception:
                continue
            rows.append({
                "name": clean_name(row["姓名"]),
                "alert_name": str(row["告警名称"]).strip(),
                "alert_time": alert_time,
                "source_file": warn_file,
            })
    return rows


def _find_timeline_csv(config, device_id):
    device_dir = os.path.join(config.TIMELINE_DIR, device_id)
    if not os.path.exists(device_dir):
        return None

    csv_files = [
        os.path.join(device_dir, filename)
        for filename in os.listdir(device_dir)
        if filename.endswith(".csv")
    ]
    if not csv_files:
        return None

    csv_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return csv_files[0]


def _read_timeline_window(csv_path, start_time, end_time):
    header = pd.read_csv(csv_path, nrows=0)
    inbed_column = _find_inbed_column(header.columns)
    if inbed_column is None:
        raise ValueError(f"timeline 缺少 inbed_flag 列: {csv_path}")
    if "body_status" not in header.columns:
        raise ValueError(f"timeline 缺少 body_status 列: {csv_path}")

    df = pd.read_csv(csv_path, usecols=["time", "body_status", inbed_column])
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])
    df = df[(df["time"] >= start_time) & (df["time"] <= end_time)].copy()
    if df.empty:
        return df, inbed_column

    df["body_status"] = df["body_status"].apply(_normalize_state)
    df[inbed_column] = df[inbed_column].apply(lambda value: 1 if _normalize_state(value) > 0 else 0)
    df = df.sort_values("time")
    return df, inbed_column


def _change_times(df, inbed_column):
    changed = (
        df["body_status"].ne(df["body_status"].shift())
        | df[inbed_column].ne(df[inbed_column].shift())
    )
    return list(df.loc[changed, "time"])


def _safe_filename_part(value):
    text = str(value).strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", "", text)
    return text or "unknown"


def _draw_overlay(df, inbed_column, device_id, person_name, alert_name, alert_time, output_file):
    if df.empty:
        return False

    fig, ax = plt.subplots(figsize=(12, 9))
    window_start = df["time"].min()
    window_end = df["time"].max()

    # inbed_flag 作为背景色：1=浅绿色在床，0=浅红色离床。
    blocks = (
        df[inbed_column].ne(df[inbed_column].shift())
    ).cumsum()
    for _, block_df in df.groupby(blocks):
        start_time = block_df["time"].iloc[0]
        end_time = block_df["time"].iloc[-1]
        inbed_value = int(block_df[inbed_column].iloc[0])
        color = "#dff3df" if inbed_value == 1 else "#ffe1df"
        ax.axvspan(start_time, end_time, color=color, alpha=0.75, linewidth=0)

    ax.step(
        df["time"],
        df["body_status"],
        where="post",
        linewidth=2.2,
        color="#1f77b4",
        label="body_status",
    )
    alert_line = ax.axvline(alert_time, color="#e60000", linewidth=3.5, linestyle="-", label="离床预警时间")
    ax.set_xlim(window_start, window_end)
    ax.set_ylim(-0.25, max(2.5, float(df["body_status"].max()) + 0.5))

    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.tick_params(axis="x", rotation=45, labelsize=9)

    ax.set_yticks(sorted(set([0, 1] + df["body_status"].dropna().astype(int).tolist())))
    ax.set_ylabel("状态值")
    ax.set_title(
        f"{person_name} | {device_id} | {alert_name} {alert_time.strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=14,
        pad=14,
    )
    ax.grid(True, axis="y", linestyle="--", alpha=0.35)
    inbed_patch = mpatches.Patch(color="#dff3df", alpha=0.75, label="inbed_flag=1 在床背景")
    outbed_patch = mpatches.Patch(color="#ffe1df", alpha=0.75, label="inbed_flag=0 离床背景")
    body_line = ax.lines[0]
    ax.legend(handles=[body_line, inbed_patch, outbed_patch, alert_line], loc="upper right")

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def generate_overlay_plots(config, minutes=10, alert_keyword="离床", output_dir=None, limit=None):
    device_map = get_device_mapping(config.DEVICE_ID_PATH, region=config.LOCATION_CONFIG.get("name"))
    warning_rows = _read_warning_rows(config, alert_keyword)
    if not warning_rows:
        logging.warning("未找到符合条件的告警记录: %s", config.WARN_DIR)
        return []

    output_dir = output_dir or os.path.join(config.OUTPUT_DIR, "leave_bed_overlay_plots")
    generated = []
    skipped = 0

    for row in warning_rows:
        if limit is not None and len(generated) >= limit:
            break

        person_name = row["name"]
        device_id = device_map.get(person_name)
        if not device_id:
            logging.warning("告警姓名未匹配到设备号，跳过: %s", person_name)
            skipped += 1
            continue

        timeline_csv = _find_timeline_csv(config, device_id)
        if not timeline_csv:
            logging.warning("未找到 timeline CSV，跳过: %s %s", person_name, device_id)
            skipped += 1
            continue

        alert_time = row["alert_time"]
        start_time = alert_time - timedelta(minutes=minutes)
        end_time = alert_time + timedelta(minutes=minutes)

        try:
            df, inbed_column = _read_timeline_window(timeline_csv, start_time, end_time)
        except Exception as e:
            logging.warning("读取 timeline 失败，跳过 %s %s: %s", person_name, device_id, e)
            skipped += 1
            continue

        if df.empty:
            logging.warning("告警前后 %s 分钟没有 timeline 数据，跳过: %s %s", minutes, person_name, alert_time)
            skipped += 1
            continue

        filename = (
            f"{alert_time.strftime('%Y%m%d_%H%M%S')}_"
            f"{_safe_filename_part(person_name)}_"
            f"{_safe_filename_part(row['alert_name'])}_"
            f"{device_id}.png"
        )
        output_file = os.path.join(output_dir, device_id, filename)
        if _draw_overlay(df, inbed_column, device_id, person_name, row["alert_name"], alert_time, output_file):
            generated.append(output_file)
            logging.info("已生成叠加图: %s", output_file)

    logging.info("离床预警叠加图完成: 生成 %s 张，跳过 %s 条", len(generated), skipped)
    return generated


def run(config):
    """流水线入口：生成离床预警前后 body_status + inbed_flag 叠加图。"""
    logging.info("=== 开始生成离床预警叠加图 ===")
    return generate_overlay_plots(config=config, minutes=10, alert_keyword="离床")


def main():
    parser = argparse.ArgumentParser(description="离床预警前后 body_status + inbed_flag 叠加图调试脚本")
    parser.add_argument("--location", "-l", required=True, help="院区代码，例如 hf/hk/nj/jy")
    parser.add_argument("--date", "-d", required=True, help="任务日期，例如 2026-05-08 或 20260508")
    parser.add_argument("--minutes", "-m", type=int, default=10, help="预警前后窗口分钟数，默认 10")
    parser.add_argument("--keyword", "-k", default="离床", help="告警名称筛选关键字，默认 离床")
    parser.add_argument("--limit", type=int, default=None, help="最多生成几张图，调试时可用")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="config.json 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")

    config_data = _load_config_data(args.config)
    if args.location not in config_data:
        raise KeyError(f"config.json 中找不到院区: {args.location}")

    target_date = _parse_date(args.date)
    config = _make_config(config_data, args.location, target_date)
    generate_overlay_plots(
        config=config,
        minutes=args.minutes,
        alert_keyword=args.keyword,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
