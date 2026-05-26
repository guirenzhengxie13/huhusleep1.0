import csv
import json
import logging
import os
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


WARNING_URL = "https://ylycare.tianyucare.com/#/organization/intelligent-care/newWarning"
ALERT_FIELDS = ["姓名", "告警名称", "告警时间"]
DEFAULT_ACCOUNT_KEY = "default"


def kill_zombie_processes():
    """清理残留 chromedriver，避免下次启动卡住。"""
    logging.info("正在清理后台残留 chromedriver 进程...")
    os.system("taskkill /f /im chromedriver.exe >nul 2>&1")


def init_driver(config):
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    if config.CRAWLER_HEADLESS:
        options.add_argument("--headless=new")

    service = Service(executable_path=config.CHROME_DRIVER)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver


def load_crawler_accounts(config):
    account_path = getattr(config, "CRAWLER_ACCOUNTS_PATH", None)
    if not account_path or not os.path.exists(account_path):
        raise FileNotFoundError(f"找不到爬虫账号配置文件: {account_path}")

    with open(account_path, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    if not isinstance(accounts, dict):
        raise ValueError(f"爬虫账号配置格式错误: {account_path}")
    return accounts


def get_crawler_account(config):
    accounts = load_crawler_accounts(config)
    account_key = getattr(config, "CRAWLER_ACCOUNT_KEY", DEFAULT_ACCOUNT_KEY) or DEFAULT_ACCOUNT_KEY
    account = accounts.get(account_key)
    if account is None:
        account = accounts.get(DEFAULT_ACCOUNT_KEY)
        if account is None:
            raise KeyError(f"爬虫账号配置缺少账号: {account_key}")
        logging.warning("未找到爬虫账号 %s，改用 default 账号", account_key)

    username = account.get("username")
    password = account.get("password")
    if not username or not password:
        raise ValueError(f"爬虫账号 {account_key} 缺少 username 或 password")

    return account_key, username, password


def login(driver, username, password, account_key=DEFAULT_ACCOUNT_KEY):
    driver.get(WARNING_URL)
    time.sleep(3)
    try:
        username_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='请输入账号']"))
        )
        username_input.clear()
        username_input.send_keys(username)

        password_input = driver.find_element(By.XPATH, "//input[@placeholder='请输入密码']")
        password_input.clear()
        password_input.send_keys(password)

        login_button = driver.find_element(By.XPATH, "//button[@type='button']")
        login_button.click()

        time.sleep(6)
        driver.get(WARNING_URL)
        time.sleep(6)
        _try_expand_page_size(driver)
        logging.info("已使用 %s 爬虫账号进入后台告警页面", account_key)
    except Exception as e:
        logging.warning("登录流程提示: %s", e)


def _try_expand_page_size(driver):
    """尽量把后台表格调到更大分页；失败不影响原分页爬取。"""
    try:
        size_select = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-pagination .el-select"))
        )
        size_select.click()
        option = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//li[contains(@class,'el-select-dropdown__item')]"
                "[contains(., '100') or contains(., '50')]",
            ))
        )
        option.click()
        time.sleep(2)
        logging.info("已尝试切换到更大分页，减少翻页次数")
    except Exception:
        logging.info("未找到分页大小控件，继续使用默认分页")


def warning_window(config):
    start_time_str = f"{config.file_date_obj.year}-{config.CURR_MD[:2]}-{config.CURR_MD[2:]} 21:00:00"
    end_time_str = f"{config.file_date_obj.year}-{config.NEXT_MD[:2]}-{config.NEXT_MD[2:]} 06:00:00"
    return (
        datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S"),
        datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S"),
    )


def warning_filename(config):
    start_time, end_time = warning_window(config)
    return f"告警_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}.csv"


def warning_output_path(config):
    return os.path.join(config.WARN_DIR, warning_filename(config))


def warning_file_exists(config):
    path = warning_output_path(config)
    return os.path.exists(path) and os.path.getsize(path) > 0


def _parse_alert_time(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def extract_alerts(driver, start_time, end_time):
    alerts = []
    stop_crawling = False
    try:
        time.sleep(1)
        rows = driver.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            try:
                text = row.text.strip()
                if not text:
                    continue

                cols = text.split()
                if len(cols) < 4:
                    continue

                name, alert_name = cols[0], cols[1]
                alert_time_str = f"{cols[2]} {cols[3]}"
                if str(start_time.year) not in alert_time_str and str(end_time.year) not in alert_time_str:
                    continue

                alert_time = _parse_alert_time(alert_time_str)
                if alert_time < start_time:
                    stop_crawling = True
                    break
                if alert_time > end_time:
                    continue

                alerts.append({"姓名": name, "告警名称": alert_name, "告警时间": alert_time_str})
            except Exception:
                continue
    except Exception as e:
        logging.warning("提取告警异常: %s", e)
    return alerts, stop_crawling


def next_page(driver):
    try:
        next_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'下一页') or contains(@class,'next')]"))
        )
        if next_btn.is_enabled() and "disabled" not in next_btn.get_attribute("class"):
            next_btn.click()
            time.sleep(1.5)
            return True
    except Exception:
        pass
    return False


def _crawl_alerts_for_range(driver, start_time, end_time):
    all_alerts = []
    seen = set()
    page_count = 0

    while True:
        page_count += 1
        page_alerts, stop = extract_alerts(driver, start_time, end_time)
        for alert in page_alerts:
            key = (alert["姓名"], alert["告警名称"], alert["告警时间"])
            if key in seen:
                continue
            seen.add(key)
            all_alerts.append(alert)

        if stop or not next_page(driver):
            break

    logging.info("告警页面抓取完成: 翻页 %s 次，命中 %s 条", page_count, len(all_alerts))
    return all_alerts


def _write_alerts(output_file, alerts):
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    alerts = sorted(alerts, key=lambda item: item["告警时间"])
    with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ALERT_FIELDS)
        writer.writeheader()
        writer.writerows(alerts)


def _filter_alerts(alerts, start_time, end_time):
    filtered = []
    for alert in alerts:
        try:
            alert_time = _parse_alert_time(alert["告警时间"])
        except Exception:
            continue
        if start_time <= alert_time <= end_time:
            filtered.append(alert)
    return filtered


def run(config, force=False):
    output_file = warning_output_path(config)
    if warning_file_exists(config) and not force:
        logging.info("本地告警 CSV 已存在，跳过爬取: %s", output_file)
        return output_file

    logging.info("=== 开始爬取后台告警数据 ===")
    start_time, end_time = warning_window(config)
    account_key, username, password = get_crawler_account(config)
    kill_zombie_processes()

    driver = init_driver(config)
    try:
        login(driver, username, password, account_key)
        alerts = _crawl_alerts_for_range(driver, start_time, end_time)
        _write_alerts(output_file, alerts)
        logging.info("告警爬取完成: %s 条 -> %s", len(alerts), output_file)
        return output_file
    finally:
        driver.quit()


def run_batch(configs, force=False):
    unique_configs = {}
    for config in configs:
        unique_configs[(config.LOCATION_CODE, config.FILE_DATE)] = config
    configs = list(unique_configs.values())

    pending = [config for config in configs if force or not warning_file_exists(config)]
    if not pending:
        logging.info("本次所需告警 CSV 均已存在，跳过批量爬取")
        return {config: warning_output_path(config) for config in configs}

    grouped_configs = {}
    account_infos = {}
    for config in pending:
        account_key, username, password = get_crawler_account(config)
        grouped_configs.setdefault(account_key, []).append(config)
        account_infos[account_key] = (username, password)

    logging.info("=== 批量爬取后台告警数据: %s 个任务，%s 组账号 ===", len(pending), len(grouped_configs))
    kill_zombie_processes()

    output_paths = {}
    for account_key, account_configs in grouped_configs.items():
        windows = {config: warning_window(config) for config in account_configs}
        min_start = min(window[0] for window in windows.values())
        max_end = max(window[1] for window in windows.values())
        username, password = account_infos[account_key]

        logging.info(
            "账号组 %s 批量爬取: %s 个任务 | %s -> %s",
            account_key,
            len(account_configs),
            min_start.strftime("%Y-%m-%d %H:%M:%S"),
            max_end.strftime("%Y-%m-%d %H:%M:%S"),
        )

        driver = init_driver(account_configs[0])
        try:
            login(driver, username, password, account_key)
            all_alerts = _crawl_alerts_for_range(driver, min_start, max_end)
        finally:
            driver.quit()

        for config in account_configs:
            start_time, end_time = windows[config]
            output_file = warning_output_path(config)
            alerts = _filter_alerts(all_alerts, start_time, end_time)
            _write_alerts(output_file, alerts)
            output_paths[config] = output_file
            logging.info(
                "已写入 %s %s 告警 CSV: %s 条 -> %s",
                config.LOCATION_CODE,
                config.FILE_DATE,
                len(alerts),
                output_file,
            )

    for config in configs:
        output_paths.setdefault(config, warning_output_path(config))
    return output_paths
