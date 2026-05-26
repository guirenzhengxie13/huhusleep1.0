import os
import csv
import json
import logging
import concurrent.futures
from datetime import datetime, timedelta

def extract_leave_bed_times(sleep_data_file):
    leave_bed_times = []
    with open(sleep_data_file, 'r', encoding='utf-8') as f:
        in_leave_bed_section = False
        for line in f:
            line = line.strip()
            if line == "离床事件:":
                in_leave_bed_section = True
                continue
            if in_leave_bed_section and line:
                time_str = line.split(' ')[0] + ' ' + line.split(' ')[1]
                leave_bed_times.append(datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S'))
    return leave_bed_times

def read_csv_data(csv_file, start_time=None, end_time=None):
    data = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                time_str = row.get('time')
                if not time_str:
                    continue
                try:
                    timestamp = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    if start_time and end_time:
                        if not (start_time <= timestamp <= end_time):
                            continue
                    
                    row_data = [
                        timestamp.isoformat(),
                        int(row.get('heart_rate', 0)),
                        int(row.get('respiratory_rate', 0)),
                        int(row.get('body_movement', 0)),
                        int(row.get('move_state', 0)),
                        int(row.get('body_status', 0)),
                        int(row.get('body_position', 0))
                    ]
                    data.append(row_data)
                except Exception:
                    continue
        return data
    except Exception as e:
        logging.warning(f"  读取CSV文件时出错: {e}")
        return []

def extract_data_around_time(csv_data, target_time):
    """智能锚点切片算法"""
    if not csv_data:
        return []

    closest_idx = 0
    min_diff = float('inf')
    for i, row in enumerate(csv_data):
        row_time = datetime.fromisoformat(row[0])
        diff = abs((row_time - target_time).total_seconds())
        if diff < min_diff:
            min_diff = diff
            closest_idx = i

    start_idx = closest_idx
    if csv_data[closest_idx][5] < 1:
        while start_idx > 0 and csv_data[start_idx - 1][5] < 1:
            start_idx -= 1
    else:
        while start_idx < len(csv_data) - 1 and csv_data[start_idx][5] >= 1:
            start_idx += 1

    end_idx = start_idx
    while end_idx < len(csv_data) - 1 and csv_data[end_idx][5] < 1:
        end_idx += 1

    BUFFER_LINES = 60
    final_start = max(0, start_idx - BUFFER_LINES)
    final_end = min(len(csv_data), end_idx + BUFFER_LINES)

    return csv_data[final_start:final_end]

def save_extracted_data(extracted_data, leave_bed_time, device_dir):
    if not extracted_data:
        return

    date_str = leave_bed_time.strftime('%Y-%m-%d')
    time_str = leave_bed_time.strftime('%Y%m%d_%H%M%S')
    
    date_dir = os.path.join(device_dir, date_str)
    os.makedirs(date_dir, exist_ok=True)
    filename = os.path.join(date_dir, f"{time_str}_data.json")

    first_time = datetime.fromisoformat(extracted_data[0][0])
    last_time = datetime.fromisoformat(extracted_data[-1][0])
    
    organized_data = {
        'leave_bed_time': leave_bed_time.isoformat(),
        'start_time': first_time.isoformat(),
        'end_time': last_time.isoformat(),
        'metrics': {
            'heart_rate': [], 'respiratory_rate': [], 'body_movement': [],
            'move_state': [], 'body_status': [], 'body_position': []
        }
    }

    metric_indices = {
        'heart_rate': 1, 'respiratory_rate': 2, 'body_movement': 3,
        'move_state': 4, 'body_status': 5, 'body_position': 6
    }

    for row in extracted_data:
        time_val = row[0]
        for metric, index in metric_indices.items():
            organized_data['metrics'][metric].append({
                'time': time_val,
                'value': row[index]
            })

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(organized_data, f, ensure_ascii=False, indent=2)

def process_device(device_name, config):
    device_sleep_dir = os.path.join(config.SLEEP_EVENTS_DIR, device_name)
    device_output_dir = os.path.join(config.LEAVE_BED_DIR, device_name)
    device_raw_dir = os.path.join(config.TIMELINE_DIR, device_name)

    os.makedirs(device_output_dir, exist_ok=True)

    if not os.path.exists(device_sleep_dir):
        return

    for time_dir in os.listdir(device_sleep_dir):
        time_dir_path = os.path.join(device_sleep_dir, time_dir)
        if not os.path.isdir(time_dir_path):
            continue
            
        sleep_data_file = os.path.join(time_dir_path, "sleep_data.txt")
        if not os.path.exists(sleep_data_file):
            continue
            
        leave_bed_times = extract_leave_bed_times(sleep_data_file)
        if not leave_bed_times:
            continue

        csv_files = [os.path.join(device_raw_dir, f) for f in os.listdir(device_raw_dir) if f.endswith('.csv')]
        if not csv_files:
            continue

        csv_file = csv_files[0]
        try:
            earliest_start = min([t - timedelta(minutes=30) for t in leave_bed_times])
            latest_end = max([t + timedelta(hours=3) for t in leave_bed_times])
            csv_data = read_csv_data(csv_file, earliest_start, latest_end)

            for leave_bed_time in leave_bed_times:
                try:
                    extracted_data = extract_data_around_time(csv_data, leave_bed_time)
                    save_extracted_data(extracted_data, leave_bed_time, device_output_dir)
                except Exception:
                    continue
        except Exception:
            continue
    logging.info(f"  设备 {device_name} 切片分析完成")

def run(config):
    logging.info("=== 开始智能提取离床切片 ===")
    if not os.path.exists(config.SLEEP_EVENTS_DIR):
        logging.error(f"未找到目录: {config.SLEEP_EVENTS_DIR}")
        return

    device_folders = [d for d in os.listdir(config.SLEEP_EVENTS_DIR) if os.path.isdir(os.path.join(config.SLEEP_EVENTS_DIR, d))]
    
    max_workers = min(8, len(device_folders)) if device_folders else 1
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_device, d_name, config): d_name for d_name in device_folders}
        for future in concurrent.futures.as_completed(futures):
            device_name = futures[future]
            try:
                future.result()
            except Exception as e:
                logging.error(f"处理设备 {device_name} 时出错: {e}")

    logging.info("✅ 离床切片数据准备完毕！")