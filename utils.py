import os
import re
import csv
import pytz
from datetime import datetime
from pathlib import Path

DEVICE_ROSTER_NAME = "full_device_roster.csv"

def mkdir_recursive(path):
    """递归创建目录"""
    os.makedirs(path, exist_ok=True)

def clean_name(raw_name):
    """剔除所有括号内容及空白字符，确保100%精准匹配"""
    if not raw_name:
        return ""
    name_str = str(raw_name)
    name_str = re.sub(r'[（\(].*?[）\)]', '', name_str)
    name_str = re.sub(r'\s+', '', name_str)
    return name_str

def _default_device_roster_path():
    return Path(__file__).resolve().parent / "assets" / DEVICE_ROSTER_NAME

def _normalize_text(value):
    return str(value).strip().lstrip("\ufeff") if value is not None else ""

def get_device_roster(filepath=None):
    """
    读取全项目唯一设备清单。

    当前字段来自 assets/full_device_roster.csv：
    院区, 设备号, 老人姓名, 房间床位

    后续补充房间号、失能等级、护理级别时，继续在同一个 CSV 扩展字段，
    不再从 deviceID*.txt 或院区设备 xlsx 读取设备基础信息。
    """
    roster_path = Path(filepath) if filepath else _default_device_roster_path()
    if not roster_path.exists():
        print(f"⚠️ 警告: 设备总表不存在 {roster_path}")
        return []

    rows = []
    with roster_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            device_id = _normalize_text(row.get("设备号") or row.get("deviceName") or row.get("device_id"))
            if not device_id:
                continue
            rows.append({
                "院区": _normalize_text(row.get("院区")),
                "设备号": device_id,
                "老人姓名": _normalize_text(row.get("老人姓名") or row.get("姓名") or row.get("老人")),
                "房间床位": _normalize_text(row.get("房间床位") or row.get("床位") or row.get("房间号")),
                "失能等级": _normalize_text(row.get("失能等级") or row.get("护理级别") or row.get("养老院失能评估")),
            })
    return rows

def build_device_to_location_from_roster(config_data, filepath=None):
    """用 full_device_roster.csv 建立 设备号 -> 院区代码 映射。"""
    name_to_code = {}
    for code, location_config in config_data.items():
        raw_name = _normalize_text(location_config.get("name"))
        if raw_name:
            name_to_code[raw_name] = code
            name_to_code[raw_name.replace("院区", "")] = code

    device_to_location = {}
    for row in get_device_roster(filepath):
        region = row["院区"]
        location_code = name_to_code.get(region, region)
        if location_code in config_data:
            device_to_location[row["设备号"]] = location_code
    return device_to_location

def _matches_region(row_region, region):
    if not region:
        return True
    row_region = _normalize_text(row_region)
    region = _normalize_text(region)
    return row_region == region or row_region == region.replace("院区", "") or f"{row_region}院区" == region

def get_device_mapping(filepath=None, region=None):
    """
    统一读取设备号与人名的对应关系。
    返回字典结构，既可以通过 id 查名字/楼层，也可以通过名字查 id。

    注意：filepath 仅用于兼容旧调用；当前应传入 full_device_roster.csv，
    或不传参数使用 assets/full_device_roster.csv。
    """
    device_map = {}
    for row in get_device_roster(filepath):
        if not _matches_region(row["院区"], region):
            continue
        device_id = row["设备号"]
        name = clean_name(row["老人姓名"])
        floor = row["房间床位"]
        device_map[device_id] = {
            "name": name,
            "floor": floor,
            "region": row["院区"],
            "disability_level": row["失能等级"],
        }
        if name:
            device_map[name] = device_id
    return device_map

def timestamp_to_shanghai(timestamp):
    """安全地将时间戳转换为上海时区的格式化时间字符串 (兼容10位、13位、16位)"""
    if not timestamp:
        return None

    try:
        ts = float(timestamp)
        if 1000000000000 <= ts < 10000000000000:       # 13位
            ts = ts / 1000
        elif 1000000000000000 <= ts < 10000000000000000: # 16位
            ts = ts / 1000000

        if ts < 0 or ts > 4102444800:
            return None

        tz_shanghai = pytz.timezone('Asia/Shanghai')
        dt_shanghai = datetime.fromtimestamp(ts, tz=tz_shanghai)
        return dt_shanghai.strftime('%Y-%m-%d %H:%M:%S')

    except Exception:
        return None
