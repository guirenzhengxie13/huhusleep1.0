import csv
import logging
import os
from collections import defaultdict


FILE_TYPE_SLEEP_REPORT = "sleep_report"
FILE_TYPE_VITAL_TRACK = "vital_track"

SLEEP_REPORT_SUFFIX = "睡眠报告.csv"
VITAL_TRACK_SUFFIX = "呼吸心率.csv"

SLEEP_REPORT_IID = "2.D.10"
SLEEP_REPORT_FIELD = "sleep-report-generate"
SLEEP_REPORT_DESCRIPTION = "睡眠报告"
VITAL_TRACK_IID = "2.D.30"
VITAL_TRACK_FIELD = "sleep-track-data"

REQUIRED_SOURCE_COLUMNS = {"设备ID", "时间", "值"}


def _normalize_cell(value):
    return str(value).strip().lstrip("\ufeff") if value is not None else ""


def _read_header(csv_path):
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        return [_normalize_cell(cell) for cell in next(reader, [])]


def _header_indexes(header):
    return {name: index for index, name in enumerate(header)}


def _row_value(indexes, row, column_name, default=""):
    index = indexes.get(column_name)
    if index is None or index >= len(row):
        return default
    return _normalize_cell(row[index])


def _iter_csv_paths(raw_data_dir):
    if not os.path.exists(raw_data_dir):
        return []
    return [
        os.path.join(raw_data_dir, filename)
        for filename in sorted(os.listdir(raw_data_dir))
        if filename.lower().endswith(".csv") and not filename.startswith("sorted_")
    ]


def detect_sleep_file_type(csv_path, sample_limit=80):
    """Detect raw sleep CSV type from source columns and sample rows."""
    header = _read_header(csv_path)
    indexes = _header_indexes(header)
    if not REQUIRED_SOURCE_COLUMNS.issubset(set(header)):
        return None

    scores = defaultdict(int)
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for _, row in zip(range(sample_limit), reader):
            iid = _row_value(indexes, row, "iid")
            field = _row_value(indexes, row, "字段")
            description = _row_value(indexes, row, "描述")

            if iid == VITAL_TRACK_IID or field == VITAL_TRACK_FIELD:
                scores[FILE_TYPE_VITAL_TRACK] += 1
            if (
                iid == SLEEP_REPORT_IID
                or field == SLEEP_REPORT_FIELD
                or description == SLEEP_REPORT_DESCRIPTION
            ):
                scores[FILE_TYPE_SLEEP_REPORT] += 1

    if not scores:
        return None
    return max(scores.items(), key=lambda item: item[1])[0]


def _find_by_suffix(raw_data_dir, suffix):
    return [
        path for path in _iter_csv_paths(raw_data_dir)
        if os.path.basename(path).endswith(suffix)
    ]


def _find_by_content(raw_data_dir, expected_type):
    matches = []
    for csv_path in _iter_csv_paths(raw_data_dir):
        try:
            if detect_sleep_file_type(csv_path) == expected_type:
                matches.append(csv_path)
        except Exception as e:
            logging.debug("跳过无法识别的 CSV: %s | %s", csv_path, e)
    return matches


def _select_candidate(raw_data_dir, matches, file_label):
    if not matches:
        raise FileNotFoundError(f"在 rawdata 目录中未找到{file_label} CSV: {raw_data_dir}")
    matches = sorted(matches, key=lambda path: os.path.basename(path))
    if len(matches) > 1:
        logging.warning(
            "识别到多个%s CSV，按文件名选择第一个: %s",
            file_label,
            ", ".join(os.path.basename(path) for path in matches),
        )
    return matches[0]


def find_vital_track_csv(raw_data_dir):
    """Find vital-track CSV without relying on largest-file guesses."""
    matches = _find_by_suffix(raw_data_dir, VITAL_TRACK_SUFFIX)
    if matches:
        return _select_candidate(raw_data_dir, matches, "呼吸心率")
    matches = _find_by_content(raw_data_dir, FILE_TYPE_VITAL_TRACK)
    return _select_candidate(raw_data_dir, matches, "呼吸心率")


def find_sleep_report_csv(raw_data_dir):
    """Find sleep-report CSV without relying on smallest-file guesses."""
    matches = _find_by_suffix(raw_data_dir, SLEEP_REPORT_SUFFIX)
    if matches:
        return _select_candidate(raw_data_dir, matches, "睡眠报告")
    matches = _find_by_content(raw_data_dir, FILE_TYPE_SLEEP_REPORT)
    return _select_candidate(raw_data_dir, matches, "睡眠报告")
