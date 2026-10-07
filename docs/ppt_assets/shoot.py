# -*- coding: utf-8 -*-
"""对真实运行的 Flask 服务截图。

Windows 下窗口高度有上限，所以整页长图用 CDP 的
``Page.captureScreenshot`` + ``captureBeyondViewport`` 实现（Edge/Chrome 支持）。
"""

from __future__ import annotations

import base64
import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
OUT = os.path.dirname(os.path.abspath(__file__))

WIDTH, HEIGHT = 1400, 900
SCALE = 2  # 2 倍分辨率，投影不失真


def build_driver() -> webdriver.Edge:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument(f"--window-size={WIDTH},{HEIGHT}")
    opts.add_argument(f"--force-device-scale-factor={SCALE}")
    opts.add_argument("--lang=zh-CN")
    driver = webdriver.Edge(options=opts)
    driver.set_window_size(WIDTH, HEIGHT)
    return driver


def shot_full(driver: webdriver.Edge, name: str, wait: float = 0.6) -> None:
    """整页长图（不受窗口高度上限限制）。"""
    time.sleep(wait)
    metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
    css = metrics.get("cssContentSize") or metrics["contentSize"]
    w = int(css["width"])
    h = int(css["height"])
    result = driver.execute_cdp_cmd(
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
            "fromSurface": True,
        },
    )
    path = os.path.join(OUT, name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(result["data"]))
    print(f"  [ok] {name}  css={w}x{h}  {os.path.getsize(path) / 1024:.0f} KB")


def login(driver: webdriver.Edge, username: str, password: str) -> None:
    driver.get(f"{BASE}/auth/login")
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "username")))
    driver.find_element(By.ID, "username").clear()
    driver.find_element(By.ID, "username").send_keys(username)
    driver.find_element(By.ID, "password").clear()
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.ID, "submit").click()
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "nav-user")))


def logout(driver: webdriver.Edge) -> None:
    driver.get(f"{BASE}/")
    try:
        driver.find_element(By.CSS_SELECTOR, "form.inline button[type=submit]").click()
        time.sleep(0.7)
    except Exception:
        pass


def main() -> None:
    driver = build_driver()
    try:
        print("1) 首页（未登录）")
        driver.get(f"{BASE}/")
        shot_full(driver, "01_home_anon.png")

        print("2) 登录页")
        driver.get(f"{BASE}/auth/login")
        shot_full(driver, "02_login.png")

        print("3) 登录失败提示")
        driver.find_element(By.ID, "username").send_keys("admin")
        driver.find_element(By.ID, "password").send_keys("wrong-password")
        driver.find_element(By.ID, "submit").click()
        shot_full(driver, "03_login_error.png", wait=1.0)

        print("4) 管理员登录后首页")
        login(driver, "admin", "admin123")
        shot_full(driver, "04_home_admin.png")
        logout(driver)

        print("5) 教师登录后首页")
        login(driver, "teacher", "teacher123")
        shot_full(driver, "05_home_teacher.png")
        logout(driver)

        print("6) 学生登录后首页")
        login(driver, "student", "student123")
        shot_full(driver, "06_home_student.png")
        logout(driver)

        print("7) 登出后回到登录页")
        shot_full(driver, "07_logout.png")
    finally:
        driver.quit()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
