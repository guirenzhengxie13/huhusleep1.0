import csv
import os
from datetime import datetime


DEFAULT_STATUS_PATH = os.path.join("assets", "pipeline_status.csv")
DONE_STATUS = "已完成"

FIELDS = [
    "日期",
    "院区",
    "状态",
    "任务日期",
    "院区代码",
    "开始时间",
    "更新时间",
    "错误信息",
]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _date_label(target_date):
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        return f"{dt.month}{dt.day}"
    except ValueError:
        return target_date


def _display_location(location_name):
    return str(location_name or "").replace("院区", "")


def _step_sort_key(step_key):
    if str(step_key).isdigit():
        return int(step_key)
    if step_key == "raw_data":
        return -1
    return 999


def _resume_step_from_row(row):
    if not row:
        return None

    status = str(row.get("状态") or "").strip()
    if status and status != DONE_STATUS:
        return status

    # 兼容旧状态表：曾经把断点放在“当前步骤”或“步骤编号”。
    for legacy_field in ("当前步骤", "步骤编号"):
        legacy_step = str(row.get(legacy_field) or "").strip()
        if legacy_step:
            return legacy_step

    return None


class RunStatusStore:
    """A small task progress table: one row per location/date."""

    def __init__(self, path=DEFAULT_STATUS_PATH):
        self.path = path
        self.rows = {}
        self._load()

    def _key(self, location_code, target_date):
        return (str(location_code), str(target_date))

    def _load(self):
        if not os.path.exists(self.path):
            return

        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                location_code = row.get("院区代码") or row.get("location_code", "")
                target_date = row.get("任务日期") or row.get("target_date", "")
                if not location_code or not target_date:
                    continue
                normalized = {field: row.get(field, "") for field in FIELDS}
                legacy_resume_step = _resume_step_from_row(row)
                if legacy_resume_step:
                    normalized["状态"] = legacy_resume_step
                self.rows[self._key(location_code, target_date)] = normalized

    def save(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        ordered_rows = sorted(
            self.rows.values(),
            key=lambda row: (row["任务日期"], row["院区代码"]),
        )
        with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(ordered_rows)

    def get(self, location_code, target_date):
        return self.rows.get(self._key(location_code, target_date))

    def is_task_completed(self, location_code, target_date):
        row = self.get(location_code, target_date)
        return bool(row and row.get("状态") == DONE_STATUS)

    def get_resume_step_key(self, location_code, target_date):
        row = self.get(location_code, target_date)
        if not row:
            return None
        resume_step = _resume_step_from_row(row)
        return resume_step

    def unfinished_jobs(self):
        jobs = []
        for row in self.rows.values():
            if row.get("状态") == DONE_STATUS:
                continue
            location_code = row.get("院区代码", "")
            target_date = row.get("任务日期", "")
            if location_code and target_date:
                jobs.append({"location_code": location_code, "target_date": target_date})
        return sorted(jobs, key=lambda item: (item["target_date"], item["location_code"]))

    def prioritize_unfinished(self, jobs):
        ordered = []
        seen = set()

        for job in self.unfinished_jobs():
            key = self._key(job["location_code"], job["target_date"])
            if key not in seen:
                ordered.append(job)
                seen.add(key)

        for job in jobs:
            key = self._key(job["location_code"], job["target_date"])
            if key not in seen:
                ordered.append(job)
                seen.add(key)

        return ordered

    def mark_running(self, location_code, location_name, target_date, step_key, step_name, message=""):
        key = self._key(location_code, target_date)
        row = self.rows.get(key, {field: "" for field in FIELDS})
        now = _now()

        row.update({
            "日期": _date_label(target_date),
            "院区": _display_location(location_name),
            "状态": str(step_key),
            "任务日期": target_date,
            "院区代码": location_code,
            "更新时间": now,
            "错误信息": str(message or ""),
        })
        if not row.get("开始时间"):
            row["开始时间"] = now

        self.rows[key] = row
        self.save()

    def mark_completed(self, location_code, location_name, target_date, step_key="", step_name="", message=""):
        key = self._key(location_code, target_date)
        row = self.rows.get(key, {field: "" for field in FIELDS})
        now = _now()

        row.update({
            "日期": _date_label(target_date),
            "院区": _display_location(location_name),
            "状态": DONE_STATUS,
            "任务日期": target_date,
            "院区代码": location_code,
            "更新时间": now,
            "错误信息": str(message or ""),
        })
        if not row.get("开始时间"):
            row["开始时间"] = now

        self.rows[key] = row
        self.save()

    def mark_failed(self, location_code, location_name, target_date, step_key, step_name, message=""):
        key = self._key(location_code, target_date)
        row = self.rows.get(key, {field: "" for field in FIELDS})
        now = _now()

        row.update({
            "日期": _date_label(target_date),
            "院区": _display_location(location_name),
            "状态": str(step_key),
            "任务日期": target_date,
            "院区代码": location_code,
            "更新时间": now,
            "错误信息": str(message or ""),
        })
        if not row.get("开始时间"):
            row["开始时间"] = now

        self.rows[key] = row
        self.save()

    def should_skip_step(self, location_code, target_date, step_key):
        resume_step = self.get_resume_step_key(location_code, target_date)
        if not resume_step:
            return False
        return _step_sort_key(step_key) < _step_sort_key(resume_step)
