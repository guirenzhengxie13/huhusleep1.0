import os
os.environ["MPLBACKEND"] = "Agg"
import matplotlib
matplotlib.use("Agg")

import json
import logging
import shutil
from datetime import datetime, timedelta

from config import Config
from crawler import warning_crawler
from pipeline.analysis import abnormal_analysis, excel, inbed_flag_anomaly, leave_bed_overlay_debug, plotter, report, slicer, sleep_evt
from pipeline.importing import data_split, raw_importer_v2
from pipeline.run_status import RunStatusStore


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")

CONFIG_FILE_PATH = "config.json"
IMPORT_DIR = r"C:\Users\Lenovo\Downloads"

STEPS_MAP = {
    "1": ("数据拆分", data_split.run),
    "2": ("睡眠事件提取", sleep_evt.run),
    "3": ("智能切片", slicer.run),
    "4": ("生成文本报告", report.run),
    "5": ("图表生成", plotter.run),
    "6": ("后台告警爬取", warning_crawler.run),
    "7": ("异常分析轨迹图", abnormal_analysis.run),
    "8": ("Excel 报表合成", excel.run),
    "9": ("明细体征图表生成", plotter.run_detail_plots),
    "10": ("离床预警叠加图", leave_bed_overlay_debug.run),
    "11": ("inbed_flag 异常检测", inbed_flag_anomaly.run),
}

RAW_DATA_STEP_KEY = "raw_data"
RAW_DATA_STEP_NAME = "原始CSV归档检查"


def load_config_data():
    if not os.path.exists(CONFIG_FILE_PATH):
        raise FileNotFoundError(f"找不到配置文件: {CONFIG_FILE_PATH}")
    with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def make_config(config_data, location_code, target_date):
    if location_code not in config_data:
        raise KeyError(f"config.json 中找不到院区配置: {location_code}")

    location_config = dict(config_data[location_code])
    location_config["code"] = location_code
    return Config(location_config, target_date)


def clear_output_folder(config):
    if os.path.exists(config.OUTPUT_DIR):
        shutil.rmtree(config.OUTPUT_DIR)
        logging.info("分析输出目录已重置: %s", config.OUTPUT_DIR)


def _location_name(config_data, location_code):
    return config_data.get(location_code, {}).get("name", location_code)


def _selected_steps(config_data, location_code):
    return config_data.get(location_code, {}).get("tasks", [])


def _job(location_code, target_date):
    return {"location_code": location_code, "target_date": target_date}


def _build_range_jobs(location_code, start_date_obj, end_date_obj):
    jobs = []
    current = start_date_obj
    while current <= end_date_obj:
        jobs.append(_job(location_code, current.strftime("%Y-%m-%d")))
        current += timedelta(days=1)
    return jobs


def prefetch_warning_data(jobs, config_data, status_store):
    warning_configs = []

    for job in jobs:
        location_code = job["location_code"]
        target_date = job["target_date"]

        if "6" not in _selected_steps(config_data, location_code):
            continue
        if status_store.is_task_completed(location_code, target_date):
            logging.info("任务已完成，跳过告警预取: %s %s", location_code, target_date)
            continue
        if status_store.should_skip_step(location_code, target_date, "6"):
            logging.info("中断任务已越过告警步骤，跳过告警预取: %s %s", location_code, target_date)
            continue

        config = make_config(config_data, location_code, target_date)
        if warning_crawler.warning_file_exists(config):
            logging.info("本地告警 CSV 已存在，跳过告警预取: %s %s", location_code, target_date)
            continue

        warning_configs.append(config)

    if not warning_configs:
        return

    try:
        warning_crawler.run_batch(warning_configs)
    except Exception as e:
        logging.error("批量告警爬取失败，流水线内第 6 步会按需重试: %s", e, exc_info=True)
        return


class WarningBatchContext:
    def __init__(self, jobs, config_data, status_store):
        self.jobs = jobs
        self.config_data = config_data
        self.status_store = status_store
        self.has_prefetched = False

    def prefetch_once(self):
        if self.has_prefetched:
            return
        self.has_prefetched = True
        prefetch_warning_data(self.jobs, self.config_data, self.status_store)


def run_pipeline(location_code, target_date, config_data=None, status_store=None, skip_completed=True, warning_batch_context=None):
    config_data = config_data or load_config_data()
    status_store = status_store or RunStatusStore()

    if skip_completed and status_store.is_task_completed(location_code, target_date):
        logging.info("任务已完成，按状态表跳过: %s %s", location_code, target_date)
        return True

    config = make_config(config_data, location_code, target_date)
    location_name = _location_name(config_data, location_code)
    selected_steps = _selected_steps(config_data, location_code)
    resume_step_key = status_store.get_resume_step_key(location_code, target_date)

    logging.info("\n%s\n睡眠报告系统 | 院区: %s | 日期: %s\n%s", "=" * 50, location_name, config.FILE_DATE, "=" * 50)
    if resume_step_key:
        resume_step_name = STEPS_MAP.get(resume_step_key, (RAW_DATA_STEP_NAME,))[0]
        logging.info("检测到断点: [%s] %s，本次从该步骤继续执行", resume_step_key, resume_step_name)

    if skip_completed and status_store.should_skip_step(location_code, target_date, RAW_DATA_STEP_KEY):
        logging.info("步骤 [%s] %s 已早于上次中断点，按状态表跳过", RAW_DATA_STEP_KEY, RAW_DATA_STEP_NAME)
    else:
        try:
            status_store.mark_running(location_code, location_name, target_date, RAW_DATA_STEP_KEY, RAW_DATA_STEP_NAME)
            raw_importer_v2.ensure_raw_data(config, config_data, IMPORT_DIR, os.getcwd())
        except Exception as e:
            status_store.mark_failed(location_code, location_name, target_date, RAW_DATA_STEP_KEY, RAW_DATA_STEP_NAME, e)
            logging.error("自动识别归档数据失败，已终止 %s 的后续分析流程: %s", target_date, e, exc_info=True)
            return False

    accurate_leave_data = None

    for step_key in selected_steps:
        if step_key not in STEPS_MAP:
            continue

        step_name, step_func = STEPS_MAP[step_key]
        if skip_completed and status_store.should_skip_step(location_code, target_date, step_key):
            logging.info("步骤 [%s] %s 已早于上次中断点，按状态表跳过", step_key, step_name)
            continue

        if step_key == "1":
            clear_output_folder(config)

        logging.info("运行步骤 [%s]: %s", step_key, step_name)
        status_store.mark_running(location_code, location_name, target_date, step_key, step_name)

        try:
            if step_key == "6" and warning_batch_context is not None:
                warning_batch_context.prefetch_once()

            if step_key == "5":
                accurate_leave_data = step_func(config)
            elif step_key == "8":
                if accurate_leave_data is None:
                    if os.path.exists(config.ACCURATE_JSON_PATH):
                        with open(config.ACCURATE_JSON_PATH, "r", encoding="utf-8") as f:
                            accurate_leave_data = json.load(f)
                    else:
                        accurate_leave_data = {}
                step_func(config, accurate_leave_data)
            else:
                step_func(config)
        except Exception as e:
            status_store.mark_failed(location_code, location_name, target_date, step_key, step_name, e)
            logging.error("流水线步骤 [%s] %s 意外中断: %s", step_key, step_name, e, exc_info=True)
            return False

    status_store.mark_completed(location_code, location_name, target_date, selected_steps[-1] if selected_steps else "", "已完成")
    logging.info("\n%s (%s) 流程执行完毕\n", location_name, location_code)
    return True


def run_jobs(jobs, config_data, status_store, pause_between_days=False):
    original_count = len(jobs)
    queued_count = register_jobs_in_status(jobs, config_data, status_store)
    if queued_count:
        logging.info("已将 %s 个新任务写入状态表，后续中断可继续恢复。", queued_count)

    jobs = status_store.prioritize_unfinished(jobs)
    if len(jobs) > original_count:
        logging.info("检测到状态表中存在未完成任务，已优先加入本次队列。")

    warning_batch_context = WarningBatchContext(jobs, config_data, status_store)

    for index, job in enumerate(jobs):
        logging.info("任务: [%s] %s", job["location_code"], job["target_date"])
        run_pipeline(
            job["location_code"],
            job["target_date"],
            config_data=config_data,
            status_store=status_store,
            warning_batch_context=warning_batch_context,
        )

        if pause_between_days and index < len(jobs) - 1:
            user_action = input(f"\n{job['target_date']} 处理完毕。按回车跑下一天，或输入 Q 紧急刹车：")
            if user_action.strip().upper() == "Q":
                print("已收到指令，安全终止流水线。")
                break


def register_jobs_in_status(jobs, config_data, status_store):
    queued_count = 0
    for job in jobs:
        location_code = job["location_code"]
        target_date = job["target_date"]
        location_name = _location_name(config_data, location_code)
        if status_store.mark_queued(location_code, location_name, target_date, RAW_DATA_STEP_KEY):
            queued_count += 1
    return queued_count


if __name__ == "__main__":
    LOCATION_CODE = ""
    USER_INPUT = "auto"

    config_data = load_config_data()
    status_store = RunStatusStore()

    yesterday_obj = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday_obj.strftime("%Y-%m-%d")

    location_code = LOCATION_CODE.strip()
    input_str = USER_INPUT.strip().lower()

    if input_str == "auto" or (not location_code and not input_str):
        print(f"启动自动识别模式：扫描 {IMPORT_DIR} 中的 CSV。")
        try:
            jobs = raw_importer_v2.discover_and_import(IMPORT_DIR, CONFIG_FILE_PATH, os.getcwd())
            if not jobs and not status_store.unfinished_jobs():
                print("没有识别到可运行的完整 CSV 数据组，状态表里也没有未完成任务。")
            run_jobs(jobs, config_data, status_store)
        except Exception as e:
            logging.error("自动识别模式启动失败: %s", e, exc_info=True)

    elif not input_str:
        if not location_code:
            raise ValueError("默认模式需要先设置 LOCATION_CODE，或将 USER_INPUT 设置为 'auto'")
        jobs = [_job(location_code, yesterday_str)]
        print(f"启动默认模式：处理 [{location_code}] 昨天 ({yesterday_str}) 的数据。")
        run_jobs(jobs, config_data, status_store)

    elif input_str.startswith("f"):
        try:
            if not location_code:
                raise ValueError("步进模式需要先设置 LOCATION_CODE")

            raw_date = input_str[1:]
            start_date_obj = datetime.strptime(raw_date, "%Y%m%d")
            jobs = _build_range_jobs(location_code, start_date_obj, yesterday_obj)

            print(f"启动步进模式：[{location_code}] 从 {start_date_obj.strftime('%Y-%m-%d')} 跑到 {yesterday_str}。")
            run_jobs(jobs, config_data, status_store, pause_between_days=True)
        except ValueError:
            print("日期格式解析失败。请确保 'f' 后面紧跟 8 位数字，例如 f20260420")

    else:
        try:
            if not location_code:
                raise ValueError("单日模式需要先设置 LOCATION_CODE")

            target_date = datetime.strptime(input_str, "%Y%m%d").strftime("%Y-%m-%d")
            jobs = [_job(location_code, target_date)]
            print(f"启动单日模式：处理 [{location_code}] {target_date} 的数据。")
            run_jobs(jobs, config_data, status_store)
        except ValueError:
            print("日期格式解析失败。请输入正确的 8 位纯数字日期，例如 20260420")
