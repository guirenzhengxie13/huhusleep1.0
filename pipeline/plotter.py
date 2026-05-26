import os
import json
import logging
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

# 配置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

def read_json_files(json_dir):
    json_files = []
    if os.path.exists(json_dir):
        for device_name in os.listdir(json_dir):
            device_json_dir = os.path.join(json_dir, device_name)
            if os.path.isdir(device_json_dir):
                for date_dir in os.listdir(device_json_dir):
                    date_path = os.path.join(device_json_dir, date_dir)
                    if os.path.isdir(date_path):
                        for filename in os.listdir(date_path):
                            if filename.endswith('_data.json'):
                                filepath = os.path.join(date_path, filename)
                                with open(filepath, 'r', encoding='utf-8') as f:
                                    data = json.load(f)
                                    json_files.append((filename, data, date_dir, device_name))
    return json_files

def plot_unified_metric(data, leave_bed_time, metric_name, output_filename):
    times = []
    values = []
    
    for item in data:
        timestamp = datetime.fromisoformat(item['time'])
        times.append(timestamp)
        if metric_name == 'body_status':
            values.append(1 if item['value'] >= 1 else 0.3)
        else:
            values.append(item['value'])

    if not times:
        return None

    plt.figure(figsize=(15, 9))
    plt.plot(times, values, marker='o', markersize=3, linestyle='-', linewidth=2, color='#1f77b4')

    leave_bed_timestamp = datetime.fromisoformat(leave_bed_time)
    title_extra = ""
    leave_bed_start = None
    leave_bed_end = None
    leave_duration_min = 0

    if metric_name == 'body_status':
        plt.axhline(y=1, color='green', linestyle='--', linewidth=2, label='有人/无人分界线')
        target_idx = 0
        min_diff = float('inf')
        for i, t in enumerate(times):
            diff = abs((t - leave_bed_timestamp).total_seconds())
            if diff < min_diff:
                min_diff = diff
                target_idx = i

        start_idx = target_idx
        if values[target_idx] == 0.3:
            while start_idx > 0 and values[start_idx - 1] == 0.3:
                start_idx -= 1
        else:
            while start_idx < len(values) - 1 and values[start_idx] == 1:
                start_idx += 1
                
        end_idx = start_idx
        while end_idx < len(values) - 1 and values[end_idx] == 0.3:
            end_idx += 1

        leave_bed_start = times[start_idx] if values[start_idx] == 0.3 else None
        leave_bed_end = times[end_idx] if values[start_idx] == 0.3 else None

        if leave_bed_start and leave_bed_end:
            leave_duration_min = max(1, int(round((leave_bed_end - leave_bed_start).total_seconds() / 60)))
            plt.axvspan(leave_bed_start, leave_bed_end, color='lightgray', alpha=0.3, label=f'离床时间段 ({leave_duration_min} 分钟)')
            title_extra = f" | 离床时长: {leave_duration_min} 分钟"
            
        plt.ylim(0, 1.5)
        plt.yticks([0.3, 1], ['在床无人', '在床有人'], fontsize=12)

    leave_bed_value = None
    for i, time_obj in enumerate(times):
        if abs((time_obj - leave_bed_timestamp).total_seconds()) < 1:
            leave_bed_value = values[i]
            break

    if leave_bed_value is not None:
        plt.plot(leave_bed_timestamp, leave_bed_value, 'ro', markersize=10, label='离床时间点')
        plt.annotate('离床', xy=(leave_bed_timestamp, leave_bed_value),
                     xytext=(leave_bed_timestamp, leave_bed_value + max(values) * 0.1),
                     arrowprops=dict(facecolor='red', shrink=0.05), fontsize=12, color='red', weight='bold')
    else:
        plt.axvline(x=leave_bed_timestamp, color='red', linestyle='--', linewidth=2, label='离床时间')

    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    total_minutes = (times[-1] - times[0]).total_seconds() / 60
    
    if total_minutes <= 5:
        plt.gca().xaxis.set_major_locator(mdates.SecondLocator(interval=30))
    elif total_minutes <= 20:
        plt.gca().xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
    elif total_minutes <= 60:
        plt.gca().xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
    else:
        plt.gca().xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
        
    plt.xticks(rotation=45, fontsize=10)

    leave_bed_str = leave_bed_timestamp.strftime('%Y-%m-%d %H:%M:%S')
    display_name = "有人/无人状态" if metric_name == 'body_status' else metric_name.replace('_', ' ').title()
    
    plt.title(f"{display_name} - 离床时间: {leave_bed_str}{title_extra}", fontsize=16, pad=20)
    plt.xlabel('时间', fontsize=12)
    plt.ylabel('状态' if metric_name == 'body_status' else '数值', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(loc='upper right', fontsize=11)
    
    plt.tight_layout()
    plt.savefig(output_filename, dpi=150, bbox_inches='tight')
    plt.close()

    if metric_name == 'body_status' and leave_bed_start and leave_bed_end:
        return {"start_time": leave_bed_start.strftime('%m-%d %H:%M:%S'), "duration": leave_duration_min}
    return None

EXCEL_METRICS = {"body_status"}
DETAIL_METRICS = {"heart_rate", "respiratory_rate", "body_movement", "move_state", "body_position"}

def process_device(device_name, json_files, global_data, config, metrics_to_plot=None):
    device_files = [(f, d, date, dev) for f, d, date, dev in json_files if dev == device_name]
    device_events = [] 
    
    # 计数器，用于统计该设备生成了多少张图
    img_count = 0

    for filename, data, date_dir, _ in device_files:
        base_name = os.path.splitext(filename)[0].replace('_data', '')
        leave_bed_time = data['leave_bed_time']
        metrics = data['metrics']

        for metric_name, metric_data in metrics.items():
            if metrics_to_plot is not None and metric_name not in metrics_to_plot:
                continue
            if not metric_data: continue
            
            target_base_dir = config.PLOT_DIR if metric_name == 'body_status' else config.PICTURE_DIR
            target_dir = os.path.join(target_base_dir, device_name, date_dir)
            os.makedirs(target_dir, exist_ok=True)
            
            output_filename = os.path.join(target_dir, f"{metric_name}_{base_name}.png")
            result = plot_unified_metric(metric_data, leave_bed_time, metric_name, output_filename)
            
            img_count += 1 # 统计增加
            if metric_name == 'body_status' and result:
                device_events.append(result)
            
            # --- 注意：这里不再单独打印每张图的生成 log ---

    if device_events:
        unique_events = {ev['start_time']: ev for ev in device_events}
        deduped_events = list(unique_events.values())
        deduped_events.sort(key=lambda x: x['start_time'])
        global_data[device_name] = deduped_events
        
    return img_count # 返回生成图片的数量

def _run_metrics(config, metrics_to_plot, log_title, write_accurate_json):
    logging.info(log_title)
    json_files = read_json_files(config.LEAVE_BED_DIR)
    device_names = sorted(list(set([dev for _, _, _, dev in json_files])))
    total_devices = len(device_names)
    
    logging.info(f"🔍 找到 {len(json_files)} 个待处理 JSON 文件，涉及 {total_devices} 个设备")
    
    global_accurate_data = {}
    for index, device_name in enumerate(device_names):
        # 执行处理
        num_imgs = process_device(device_name, json_files, global_accurate_data, config, metrics_to_plot)
        
        # --- 核心修改：每完成一个设备，输出一条汇总 log ---
        logging.info(f"📊 [{index + 1}/{total_devices}] 设备 {device_name} 处理完毕，共生成 {num_imgs} 张图表")

    if write_accurate_json:
        with open(config.ACCURATE_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(global_accurate_data, f, ensure_ascii=False, indent=2)

        logging.info(f"✅ Excel 所需图表渲染完成！数据已同步至: {config.ACCURATE_JSON_PATH}")
    else:
        logging.info("✅ 明细体征图表渲染完成！")
    return global_accurate_data

def run(config):
    return _run_metrics(
        config=config,
        metrics_to_plot=EXCEL_METRICS,
        log_title="=== 开始生成 Excel 所需离床状态图并提取精准时长 ===",
        write_accurate_json=True,
    )

def run_detail_plots(config):
    return _run_metrics(
        config=config,
        metrics_to_plot=DETAIL_METRICS,
        log_title="=== 开始生成明细体征图表（Excel 不引用） ===",
        write_accurate_json=False,
    )
