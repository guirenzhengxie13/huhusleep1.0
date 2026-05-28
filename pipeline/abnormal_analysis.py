import os
os.environ["MPLBACKEND"] = "Agg"
import matplotlib
matplotlib.use("Agg")

import re
import logging
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# 引入项目通用工具
from utils import get_device_mapping, clean_name

# 设置绘图字体（黑体）
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

INBED_FLAG_COLUMNS = ("inbed_flag", "inbedflag", "inbedFlag")


def _find_inbed_flag_column(df):
    for column in INBED_FLAG_COLUMNS:
        if column in df.columns:
            return column
    return None


def _normalize_inbed_flag(value):
    if pd.isna(value):
        return 0

    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "1.0", "true", "yes", "y", "在床", "有人", "inbed", "in_bed"}:
            return 1
        if text in {"0", "0.0", "false", "no", "n", "离床", "无人", "outbed", "out_bed"}:
            return 0

    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0
    return 1 if numeric_value > 0 else 0


def generate_24h_summary(device_id, csv_path, save_path):
    """
    核心绘图函数：生成 24 小时轨迹图
    """
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return
            
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time')

        # 状态判定：使用设备上报的 inbed_flag，1 为在床，0 为离床。
        flag_column = _find_inbed_flag_column(df)
        if flag_column is None:
            logging.warning(f"⚠️ 设备 {device_id} 时序文件缺少 inbed_flag 列，跳过异常轨迹图: {csv_path}")
            return

        df['state'] = df[flag_column].apply(_normalize_inbed_flag).astype(int)
        
        # 计算连续区间
        df['block'] = (df['state'] != df['state'].shift()).cumsum()
        summary = df.groupby(['block', 'state'])['time'].agg(['min', 'max']).reset_index()
        
        fig, ax = plt.subplots(figsize=(22, 6.5))
        
        # 锁定时间轴：当天 18:00 到 次日 08:00
        first_time = df['time'].min()
        if first_time.hour < 8:
            base_date = first_time.date() - timedelta(days=1)
        else:
            base_date = first_time.date()
            
        plot_start = datetime.combine(base_date, datetime.min.time()) + timedelta(hours=18)
        plot_end = plot_start + timedelta(hours=14)
        
        total_start_num = mdates.date2num(plot_start)
        total_end_num = mdates.date2num(plot_end)

        # 4级错层标注配置
        y_levels = [1.25, 1.65, 2.05, 2.45]
        last_x_at_level = [0.0] * len(y_levels) 
        min_gap = 20 / (24 * 60.0) # 20分钟的物理间距

        for _, row in summary.iterrows():
            start_num = mdates.date2num(row['min'])
            end_num = mdates.date2num(row['max'])
            width_num = end_num - start_num
            duration_min = int((row['max'] - row['min']).total_seconds() // 60)
            
            # 画底部的状态色块
            color = '#1f77b4' if row['state'] == 1 else '#e0e0e0'
            ax.broken_barh([(start_num, width_num)], (0, 1), facecolors=color)
            
            # 标注逻辑
            if duration_min >= 1: 
                center_x = start_num + width_num / 2
                if center_x < total_start_num or center_x > total_end_num:
                    continue
                
                dur_str = f"{duration_min//60}h{duration_min%60}m" if duration_min >= 60 else f"{duration_min}分"
                status_str = "在床" if row['state'] == 1 else "离床"

                if duration_min >= 90:
                    ax.text(center_x, 0.5, f"{row['min'].strftime('%H:%M')}\n{dur_str}\n{status_str}", 
                            ha='center', va='center', color='white' if row['state']==1 else 'black', 
                            fontsize=12, weight='bold')
                else:
                    for i in range(len(y_levels)):
                        if center_x - last_x_at_level[i] >= min_gap:
                            y_pos = y_levels[i]
                            last_x_at_level[i] = center_x
                            ax.annotate(f"{row['min'].strftime('%H:%M:%S')}\n{dur_str} {status_str}",
                                        xy=(center_x, 1.0), xytext=(center_x, y_pos),
                                        ha='center', va='center', fontsize=9,
                                        arrowprops=dict(arrowstyle="-|>", color='#555555', lw=1.0),
                                        bbox=dict(boxstyle="round,pad=0.2", fc="#f8f9fa", ec="#cccccc", alpha=0.9))
                            break

        ax.set_xlim(total_start_num, total_end_num)
        ax.set_ylim(0, 2.9)
        ax.set_yticks([])   
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.grid(True, axis='x', linestyle='--', alpha=0.5)
        
        plt.title(f"设备 {device_id} 夜间状态轨迹图 | 起始日期: {plot_start.strftime('%Y-%m-%d')}", fontsize=15, pad=15)
        
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=120, bbox_inches='tight')
        plt.close()
        
    except Exception as e:
        logging.error(f"⚠️ 设备 {device_id} 轨迹图生成失败: {e}")

def run(config):
    """
    流水线入口：自动识别“需人工排查”的设备并绘图
    """
    logging.info("=== 开始生成异常设备 24h 轨迹分析图 ===")
    
    # 1. 获取设备映射和睡眠报告路径
    device_map = get_device_mapping(config.DEVICE_ID_PATH, region=config.LOCATION_CONFIG.get("name"))
    report_path = os.path.join(config.REPORT_DIR, "睡眠报告.txt")
    
    if not os.path.exists(report_path):
        logging.warning("⚠️ 未找到睡眠报告，无法筛选异常设备。")
        return

    # 2. 扫描报告，提取需要排查的设备 ID
    target_devices = []
    with open(report_path, 'r', encoding='utf-8') as f:
        for line in f:
            if "需人工排查" in line or "需要分析" in line:
                match = re.search(r"姓名：(.*?)\s*\|", line)
                if match:
                    p_name = clean_name(match.group(1))
                    if p_name in device_map:
                        target_devices.append(device_map[p_name])

    target_devices = list(set(target_devices))
    if not target_devices:
        logging.info("💡 今日无异常设备，无需生成额外轨迹图。")
        return

    logging.info(f"🔍 识别到 {len(target_devices)} 台异常设备，正在绘制轨迹...")

    # 3. 遍历绘图
    for dev_id in target_devices:
        # 寻找对应的时序 CSV 文件
        dev_timeline_dir = os.path.join(config.TIMELINE_DIR, dev_id)
        if not os.path.exists(dev_timeline_dir):
            continue
            
        csv_files = [f for f in os.listdir(dev_timeline_dir) if f.endswith('.csv')]
        if csv_files:
            csv_path = os.path.join(dev_timeline_dir, csv_files[0])
            # 图片统一存放在 body_status_plots 下的设备文件夹内
            save_path = os.path.join(config.PLOT_DIR, dev_id, "00_24h_hr_summary.png")
            
            generate_24h_summary(dev_id, csv_path, save_path)
            logging.info(f"📊 已生成轨迹图: {dev_id}")

    logging.info("✅ 异常设备分析图表处理完毕！")
