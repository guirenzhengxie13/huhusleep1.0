import os
import csv
import json
import re
import logging
from utils import timestamp_to_shanghai
from pipeline.file_detector import find_sleep_report_csv

def run(config):
    logging.info("=== 开始解析睡眠事件 (Sleep Events) ===")
    
    try:
        input_file = find_sleep_report_csv(config.RAW_DATA_DIR)
    except FileNotFoundError as e:
        logging.error("错误: %s", e)
        return

    logging.info("使用睡眠报告 CSV 提取事件: %s", input_file)
    
    os.makedirs(config.SLEEP_EVENTS_DIR, exist_ok=True)

    data_by_device = {}
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # 跳过表头
        for row in reader:
            if len(row) < 6:
                continue
            device_id = row[0]
            timestamp = row[4]
            value = row[5]

            if device_id not in data_by_device:
                data_by_device[device_id] = []
            data_by_device[device_id].append({'timestamp': timestamp, 'value': value})

    for device_id, data_list in data_by_device.items():
        data_list.sort(key=lambda x: x['timestamp'])
        device_dir = os.path.join(config.SLEEP_EVENTS_DIR, device_id)
        os.makedirs(device_dir, exist_ok=True)

        for item in data_list:
            timestamp = item['timestamp']
            value = item['value']
            
            sleep_start, sleep_end, sleep_events = None, None, None

            try:
                if '"data":"' in value:
                    inner_json_match = re.search(r'"data":"(.*)"', value)
                    if inner_json_match:
                        inner_json_str = inner_json_match.group(1).replace('\\"', '"')
                        inner_json = json.loads(inner_json_str)
                        sleep_start = inner_json.get('sleep_start')
                        sleep_end = inner_json.get('sleep_end')
                        sleep_events = inner_json.get('sleep_events')
                else:
                    json_data = json.loads(value)
                    sleep_start = json_data.get('sleep_start')
                    sleep_end = json_data.get('sleep_end')
                    sleep_events = json_data.get('sleep_events')
            except json.JSONDecodeError:
                pass

            if sleep_start is not None or sleep_end is not None or sleep_events is not None:
                time_dir = os.path.join(device_dir, timestamp)
                os.makedirs(time_dir, exist_ok=True)
                
                output_file = os.path.join(time_dir, 'sleep_data.txt')
                with open(output_file, 'w', encoding='utf-8') as out_f:
                    if sleep_start is not None:
                        shanghai_time = timestamp_to_shanghai(sleep_start)
                        out_f.write(f"sleep_start: {shanghai_time} ({sleep_start})\n")
                    if sleep_end is not None:
                        shanghai_time = timestamp_to_shanghai(sleep_end)
                        out_f.write(f"sleep_end: {shanghai_time} ({sleep_end})\n")
                    if sleep_events is not None:
                        out_f.write(f"sleep_events: {sleep_events}\n")
                        
                        翻身事件 = []
                        离床事件 = []
                        if isinstance(sleep_events, list) and len(sleep_events) >= 2:
                            start_ts = int(sleep_start) if sleep_start else None
                            end_ts = int(sleep_end) if sleep_end else None

                            for i in range(0, len(sleep_events), 2):
                                if i + 1 < len(sleep_events):
                                    status = sleep_events[i]
                                    event_time = sleep_events[i + 1]
                                    event_ts = int(event_time)
                                    
                                    in_range = True
                                    if start_ts and end_ts:
                                        in_range = start_ts <= event_ts <= end_ts

                                    if in_range:
                                        shanghai_evt_time = timestamp_to_shanghai(event_time)
                                        if status == 1:
                                            翻身事件.append(f"{shanghai_evt_time} ({event_time})")
                                        elif status == 2:
                                            离床事件.append(f"{shanghai_evt_time} ({event_time})")
                        
                        out_f.write("翻身事件:\n")
                        for event in 翻身事件:
                            out_f.write(f"  {event}\n")
                        out_f.write("离床事件:\n")
                        for event in 离床事件:
                            out_f.write(f"  {event}\n")

    logging.info("✅ 睡眠事件提取完成！")
