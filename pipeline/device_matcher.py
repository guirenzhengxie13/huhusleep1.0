import csv
import os
import re
from collections import Counter


DEVICE_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{16}$")
DEFAULT_DEVICE_COLUMNS = ("deviceName", "device_id", "设备编号", "deviceId", "device")


def normalize_cell(value):
    return str(value).strip().lstrip("\ufeff") if value is not None else ""


def is_device_id(value):
    return bool(DEVICE_ID_PATTERN.fullmatch(normalize_cell(value)))


def extract_device_ids_from_csv(csv_path, preferred_columns=DEFAULT_DEVICE_COLUMNS, max_rows=None):
    device_ids = []
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        raw_rows = [
            [normalize_cell(cell) for cell in row]
            for row in csv.reader(f)
            if any(normalize_cell(cell) for cell in row)
        ]
        if not raw_rows:
            return device_ids

        fieldnames = raw_rows[0]
        device_column = next((name for name in preferred_columns if name in fieldnames), None)
        device_index = fieldnames.index(device_column) if device_column else None

        for index, row in enumerate(raw_rows[1:]):
            if max_rows is not None and index >= max_rows:
                break

            if device_index is not None:
                value = normalize_cell(row[device_index] if device_index < len(row) else "")
                if is_device_id(value):
                    device_ids.append(value)
                continue

            for value in row:
                text = normalize_cell(value)
                if is_device_id(text):
                    device_ids.append(text)
    return device_ids


def detect_group(device_ids, device_to_group):
    counter = Counter()
    for device_id in device_ids:
        group = device_to_group.get(device_id)
        if group:
            counter[group] += 1

    if not counter:
        return None, {}
    return counter.most_common(1)[0][0], dict(counter)


def build_device_group_from_regions(regions, device_index=2):
    device_to_group = {}
    for group_name, rows in regions.items():
        for row in rows:
            if len(row) <= device_index:
                continue
            device_id = normalize_cell(row[device_index])
            if is_device_id(device_id):
                device_to_group[device_id] = group_name
    return device_to_group


def ensure_clean_target_for_move(target_path, backup_suffix):
    if not os.path.exists(target_path):
        return

    root, ext = os.path.splitext(target_path)
    backup_path = f"{root}_backup_{backup_suffix}{ext}"
    index = 2
    while os.path.exists(backup_path):
        backup_path = f"{root}_backup_{backup_suffix}_{index}{ext}"
        index += 1
    os.replace(target_path, backup_path)
