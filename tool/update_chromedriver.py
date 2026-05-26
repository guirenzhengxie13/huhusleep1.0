import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DRIVER_PATH = os.path.join(PROJECT_ROOT, "assets", "chromedriver.exe")
KNOWN_GOOD_URL = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
LAST_KNOWN_GOOD_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"


def _run(command):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def find_chrome_exe():
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path

    try:
        path = _run(["where", "chrome"]).splitlines()[0]
        if os.path.exists(path):
            return path
    except Exception:
        pass

    raise FileNotFoundError("未找到本机 Chrome，请确认已安装 Google Chrome")


def chrome_version(chrome_exe):
    powershell = (
        f"(Get-Item -LiteralPath '{chrome_exe}').VersionInfo.ProductVersion"
    )
    return _run(["powershell", "-NoProfile", "-Command", powershell])


def load_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def find_download_url(version, platform):
    known = load_json(KNOWN_GOOD_URL)
    versions = known.get("versions", [])
    target = next((item for item in versions if item.get("version") == version), None)

    if target is None:
        major = version.split(".", 1)[0]
        same_major = [item for item in versions if item.get("version", "").startswith(f"{major}.")]
        if not same_major:
            raise RuntimeError(f"Chrome for Testing 清单里找不到 Chrome {version} 或同主版本 {major}")
        target = same_major[-1]
        print(f"未找到精确版本 {version}，改用同主版本最新驱动 {target['version']}")

    for download in target.get("downloads", {}).get("chromedriver", []):
        if download.get("platform") == platform:
            return target["version"], download["url"]

    last_known = load_json(LAST_KNOWN_GOOD_URL)
    stable = last_known.get("channels", {}).get("Stable", {})
    for download in stable.get("downloads", {}).get("chromedriver", []):
        if download.get("platform") == platform:
            print(f"当前清单缺少 {platform} 下载，改用 Stable {stable.get('version')}")
            return stable.get("version"), download["url"]

    raise RuntimeError(f"找不到 {platform} 的 chromedriver 下载地址")


def current_driver_version(driver_path):
    if not os.path.exists(driver_path):
        return ""
    try:
        return _run([driver_path, "--version"])
    except Exception:
        return ""


def _version_from_driver_text(driver_text):
    parts = driver_text.split()
    return parts[1] if len(parts) >= 2 and parts[0] == "ChromeDriver" else ""


def _same_major_version(version_a, version_b):
    return version_a.split(".", 1)[0] == version_b.split(".", 1)[0]


def install_driver(url, driver_path, backup=True):
    os.makedirs(os.path.dirname(driver_path), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="huhusleep_chromedriver_") as temp_dir:
        zip_path = os.path.join(temp_dir, "chromedriver.zip")
        extract_dir = os.path.join(temp_dir, "extract")
        with urllib.request.urlopen(url, timeout=120) as response, open(zip_path, "wb") as f:
            shutil.copyfileobj(response, f)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

        new_driver = None
        for root, _, files in os.walk(extract_dir):
            if "chromedriver.exe" in files:
                new_driver = os.path.join(root, "chromedriver.exe")
                break
        if not new_driver:
            raise RuntimeError("下载包里没有 chromedriver.exe")

        if backup and os.path.exists(driver_path):
            backup_path = os.path.join(
                os.path.dirname(driver_path),
                f"chromedriver_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.exe",
            )
            shutil.copy2(driver_path, backup_path)
            print(f"已备份旧驱动: {backup_path}")

        shutil.copy2(new_driver, driver_path)


def main():
    parser = argparse.ArgumentParser(description="自动下载与本机 Chrome 匹配的 ChromeDriver")
    parser.add_argument("--driver-path", default=DEFAULT_DRIVER_PATH, help="chromedriver.exe 输出路径")
    parser.add_argument("--platform", default="win64", choices=["win64", "win32"], help="ChromeDriver 平台")
    parser.add_argument("--no-backup", action="store_true", help="不备份旧 chromedriver")
    args = parser.parse_args()

    chrome_exe = find_chrome_exe()
    version = chrome_version(chrome_exe)
    print(f"Chrome: {version}")
    print(f"Chrome path: {chrome_exe}")

    current = current_driver_version(args.driver_path)
    current_version = _version_from_driver_text(current)
    if current_version == version:
        print(f"当前驱动已经精确匹配: {current}")
        return
    if current_version and _same_major_version(current_version, version):
        print(f"当前驱动主版本已匹配，可以继续使用: {current}")
        print("如需强制下载同小版本驱动，请先删除 assets/chromedriver.exe 后重跑。")
        return

    driver_version, url = find_download_url(version, args.platform)
    print(f"ChromeDriver target: {driver_version}")
    print(f"Download: {url}")

    install_driver(url, args.driver_path, backup=not args.no_backup)
    print(f"安装完成: {current_driver_version(args.driver_path)}")


if __name__ == "__main__":
    if os.name != "nt":
        print("当前脚本按 Windows Chrome 路径编写。", file=sys.stderr)
    main()
