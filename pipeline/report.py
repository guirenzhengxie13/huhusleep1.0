import os
import csv
import logging
from datetime import datetime
from utils import get_device_mapping

def analyze_unprocessed_devices(unprocessed_devices, config):
    """回查 timeline 诊断未生成报告的设备"""
    for device in unprocessed_devices:
        device_id = device['device_id']
        device_timeline_dir = os.path.join(config.TIMELINE_DIR, device_id)
        
        if not os.path.exists(device_timeline_dir):
            device['status'] = "设备离线 (未接收到任何数据)"
            continue
            
        csv_files = [f for f in os.listdir(device_timeline_dir) if f.endswith('.csv')]
        if not csv_files:
            device['status'] = "设备离线 (存在目录但无CSV文件)"
            continue
            
        csv_path = os.path.join(device_timeline_dir, csv_files[0])
        total_hr, valid_count = 0, 0
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        hr = int(row.get('heart_rate', 0))
                    except ValueError:
                        hr = 0
                    total_hr += hr
                    valid_count += 1
                    
            if valid_count == 0:
                device['status'] = "设备离线 (CSV数据为空)"
            else:
                avg_hr = total_hr / valid_count
                if avg_hr < 10:
                    device['status'] = f"无人在床 (全天平均心率: {avg_hr:.1f})"
                else:
                    device['status'] = f"需人工排查 (全天平均心率: {avg_hr:.1f}，可能有数据但算法未出报告)"
                    
        except Exception as e:
            device['status'] = f"文件读取异常 ({e})"
            
    return unprocessed_devices

def run(config):
    logging.info("=== 开始生成睡眠报告并排查异常设备 ===")
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    
    device_name_map = get_device_mapping(config.DEVICE_ID_PATH, region=config.LOCATION_CONFIG.get("name"))
    total_devices = len(device_name_map)
    # 因为设备映射做了双向映射（ID->Dict, Name->ID），这里只遍历真实设备ID
    real_devices = {k: v for k, v in device_name_map.items() if isinstance(v, dict)}
    
    data = []
    processed_devices = 0
    unprocessed_devices = []
    
    for device_id, info in real_devices.items():
        device_dir = os.path.join(config.SLEEP_EVENTS_DIR, device_id)
        device_processed = False
        
        if os.path.exists(device_dir):
            timestamp_dirs = sorted(os.listdir(device_dir))
            if timestamp_dirs:
                first_dir = timestamp_dirs[0]
                sleep_data_file = os.path.join(device_dir, first_dir, "sleep_data.txt")
                
                if os.path.exists(sleep_data_file):
                    with open(sleep_data_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    sleep_start, sleep_end = None, None
                    leave_bed_events = []
                    is_leave_bed_section = False
                    
                    for line in lines:
                        line = line.strip()
                        if line.startswith("sleep_start:"):
                            sleep_start = line.split(": ")[1].split(" (")[0]
                        elif line.startswith("sleep_end:"):
                            sleep_end = line.split(": ")[1].split(" (")[0]
                        elif line.startswith("离床事件:"):
                            is_leave_bed_section = True
                        elif line.startswith("翻身事件:"):
                            is_leave_bed_section = False
                        elif line and line.startswith("2026-") and is_leave_bed_section:
                            leave_bed_events.append(line.split(" (")[0])
                    
                    if sleep_start and sleep_end:
                        def format_time(time_str):
                            dt = datetime.fromisoformat(time_str)
                            return dt.strftime("%m-%d %H:%M:%S")
                        
                        formatted_sleep_start = format_time(sleep_start)
                        formatted_sleep_end = format_time(sleep_end)
                        
                        leave_bed_events.sort()
                        formatted_leave_bed = [format_time(ev) for ev in leave_bed_events]
                        leave_bed_str = "、".join(formatted_leave_bed) if formatted_leave_bed else ""
                        
                        record = f"{info['name']} | {info['floor']} | 入睡 {formatted_sleep_start} | 清醒 {formatted_sleep_end} | 离床时间：{leave_bed_str}"
                        data.append(record)
                        processed_devices += 1
                        device_processed = True
        
        if not device_processed:
            unprocessed_devices.append({
                "name": info['name'], "floor": info['floor'], "device_id": device_id
            })
    
    # 写入结果
    output_file = os.path.join(config.REPORT_DIR, "睡眠报告.txt")
    with open(output_file, 'w', encoding='utf-8') as f:
        for record in data:
            f.write(record + "\n")
        
        if unprocessed_devices:
            analyzed_devices = analyze_unprocessed_devices(unprocessed_devices, config)
            f.write("=" * 80 + "\n")
            f.write("今日有部分设备未生成睡眠报告，初步系统诊断如下：\n\n")
            for device in analyzed_devices:
                f.write(f"姓名：{device['name']} | 房间：{device['floor']} | 诊断结果：{device['status']}\n")
            f.write("=" * 80 + "\n")
            logging.warning("⚠️ 警告：部分设备没有睡眠数据，诊断结果已写入报告尾部！")
            
    logging.info(f"✅ 睡眠文本报告已生成，成功出报表设备: {processed_devices}/{len(real_devices)}")
