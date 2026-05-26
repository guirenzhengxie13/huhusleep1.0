import os
from pathlib import Path
from datetime import datetime, timedelta

class Config:
    # 🌟 新增 location_config 参数，接收 JSON 中对应的字典
    def __init__(self, location_config, target_date_str="2026-04-11"):
        self.LOCATION_CONFIG = location_config
        self.LOCATION_CODE = location_config.get("code", "")

        # 1. 核心日期配置
        self.FILE_DATE = target_date_str
        self.file_date_obj = datetime.strptime(self.FILE_DATE, "%Y-%m-%d")

        # 2. 从 JSON 动态读取最外层的基础路径
        self.BASE_DATA_PATH = location_config["base_data_path"]
        
        # 项目根目录使用当前项目路径，便于在重构准备目录内独立运行
        self.PROJ_ROOT = str(Path(__file__).resolve().parent)
        self.ASSETS_DIR = os.path.join(self.PROJ_ROOT, "assets")

        # 3. 核心依赖文件配置 
        # 公共文件（大家一样）：直接写死
        self.CHROME_DRIVER = os.path.join(self.ASSETS_DIR, "chromedriver.exe")
        self.CRAWLER_ACCOUNTS_PATH = os.path.join(self.ASSETS_DIR, "crawler_accounts.json")
        self.CRAWLER_ACCOUNT_KEY = location_config.get("crawler_account", "default")
        
        # 差异文件（院区不同）：从 JSON 读取文件名并拼接
        template_config_name = location_config.get("leave_bed_template_name", "leave_bed_analysis_template.json")
        self.LEAVE_BED_TEMPLATE_CONFIG = os.path.join(self.ASSETS_DIR, template_config_name)
        
        roster_name = location_config.get("device_roster_name", "full_device_roster.csv")
        self.DEVICE_ROSTER_PATH = os.path.join(self.ASSETS_DIR, roster_name)
        # 兼容旧模块命名：旧代码通过 DEVICE_ID_PATH 获取姓名/床位映射。
        self.DEVICE_ID_PATH = self.DEVICE_ROSTER_PATH

        # 4. 动态生成的日期相关的文件夹/变量 (👇 以下代码与之前完全一样，完美复用！)
        self.MONTH_DAY_FOLDER = f"{self.file_date_obj.month}{self.file_date_obj.day}"
        self.DATE_STR = self.file_date_obj.strftime("%Y%m%d")

        self.RAW_DATA_DIR = os.path.join(self.BASE_DATA_PATH, "rawdata", self.MONTH_DAY_FOLDER)
        self.TIMELINE_DIR = os.path.join(self.BASE_DATA_PATH, "timeline", self.MONTH_DAY_FOLDER)
        self.OUTPUT_DIR = os.path.join(self.BASE_DATA_PATH, "output", self.MONTH_DAY_FOLDER)
        self.WARN_DIR = os.path.join(self.BASE_DATA_PATH, "warn", self.MONTH_DAY_FOLDER)

        self.SLEEP_EVENTS_DIR = os.path.join(self.OUTPUT_DIR, "sleep_events")
        self.LEAVE_BED_DIR = os.path.join(self.OUTPUT_DIR, "leave_bed_analysis")
        self.REPORT_DIR = os.path.join(self.OUTPUT_DIR, "sleep_report")
        self.PLOT_DIR = os.path.join(self.OUTPUT_DIR, "body_status_plots")
        self.PICTURE_DIR = os.path.join(self.OUTPUT_DIR, "picture")
        
        self.ACCURATE_JSON_PATH = os.path.join(self.OUTPUT_DIR, "accurate_leave_bed.json")

        self.ensure_directories()

        # 5. 爬虫与业务常量配置
        self.CURR_MD = self.file_date_obj.strftime("%m%d")
        self.NEXT_MD = (self.file_date_obj + timedelta(days=1)).strftime("%m%d")
        self.CRAWLER_HEADLESS = True  
        self.START_TIME = "08:00:00"
        self.DURATION_TIME = 24

    def ensure_directories(self):
        for path in [
            self.BASE_DATA_PATH,
            os.path.join(self.BASE_DATA_PATH, "rawdata"),
            os.path.join(self.BASE_DATA_PATH, "timeline"),
            os.path.join(self.BASE_DATA_PATH, "output"),
            os.path.join(self.BASE_DATA_PATH, "warn"),
            self.RAW_DATA_DIR,
            self.TIMELINE_DIR,
            self.OUTPUT_DIR,
            self.WARN_DIR,
        ]:
            os.makedirs(path, exist_ok=True)
