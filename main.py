#!/usr/bin/env python3
"""
Host-Ship 自动续订脚本 - DrissionPage 版本
支持多服务器自动遍历续签、冷却时间 (CD) 自动检测等待与重试、失败/成功推送截图至 Telegram
"""

import os
import sys
import time
import re
import requests
from xvfbwrapper import Xvfb
from DrissionPage import ChromiumPage, ChromiumOptions

# ==============================================================================
# 统一日志 & Telegram 通知
# ==============================================================================
def log(msg, level="INFO"):
    prefix = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERROR]"}.get(level, "[INFO]")
    print(f"{prefix} {msg}", flush=True)

def send_tg_photo(token, chat_id, photo_path, caption, parse_mode='HTML'):
    if not token or not chat_id:
        log("未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过通知。", "WARN")
        return
    if not photo_path or not os.path.exists(photo_path):
        log(f"未找到截图文件 {photo_path}，跳过通知。", "WARN")
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(photo_path, "rb") as photo_file:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode},
                files={"photo": photo_file},
                timeout=30,
            )
        response.raise_for_status()
        log("Telegram 图片通知发送成功")
    except Exception as e:
        log(f"Telegram 图片通知异常: {e}", "ERROR")

# ==============================================================================
# 主自动化流程
# ==============================================================================
def main():
    tg_token = os.getenv("TG_BOT_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")
    username = os.getenv("PANEL_USER")
    password = os.getenv("PANEL_PASS")

    if not username or not password:
        log("请在 GitHub Secrets 中配置 PANEL_USER 和 PANEL_PASS", "ERROR")
        sys.exit(1)

    panel_url = "https://panel.host-ship.com"
    login_url = f"{panel_url}/auth/login"

    # 截图目录初始化
    screenshot_dir = "output/screenshots"
    os.makedirs(screenshot_dir, exist_ok=True)

    # 启动虚拟显示屏 (GitHub Actions 环境需要)
    vdisplay = Xvfb(width=1920, height=1080, colordepth=24)
    vdisplay.start()

    page = None
    try:
        co = ChromiumOptions()
        co.set_browser_path('/usr/bin/google-chrome')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--window-size=1920,1080')
        co.headless(False)  # 在 Xvfb 下可为 False 模拟真实界面渲染
        page = ChromiumPage(co)

        # ---------------------------------------------------------
        # 1. 登录面板
        # ---------------------------------------------------------
        log(f"访问登录页面: {login_url}")
        page.get(login_url)
        time.sleep(4)

        log("填写账号密码...")
        user_input = page.ele('css:input[name="user"], input[type="text"], input[type="email"]')
        pass_input = page.ele('css:input[name="password"], input[type="password"]')
        submit_btn = page.ele('css:button[type="submit"]')

        if user_input and pass_input and submit_btn:
            user_input.input(username)
            pass_input.input(password)
            submit_btn.click()
            time.sleep(5)
        else:
            log("找不到登录表单元素，页面结构可能已更改", "ERROR")
            err_shot = page.get_screenshot(path=f"{screenshot_dir}/login_error.png")
            send_tg_photo(tg_token, tg_chat_id, err_shot, "❌ Host-Ship 登录失败：找不到输入框")
            sys.exit(1)

        # ---------------------------------------------------------
        # 2. 遍历 Dashboard 抓取服务器并续期
        # ---------------------------------------------------------
        page.get(panel_url)
        time.sleep(4)

        # 匹配包含 "manage server" 文本的按钮或链接（忽略大小写）
        manage_btns = [el for el in page.eles('tag:button') + page.eles('tag:a') if el.text and 'manage server' in el.text.lower()]
        server_count = len(manage_btns)
        log(f"仪表盘检索到 {server_count} 个服务器待处理")

        if server_count == 0:
            log("未找到 Manage Server 按钮，可能是账号内没有机器或登录未成功", "WARN")
            err_shot = page.get_screenshot(path=f"{screenshot_dir}/dashboard_no_servers.png")
            send_tg_photo(tg_token, tg_chat_id, err_shot, "⚠️ Host-Ship：登录成功但未发现可管理的服务器")
            sys.exit(1)

        total_success = 0

        for i in range(server_count):
            server_name = f"Server_{i+1}"
            log(f"========== 开始处理 {server_name} ==========")
            
            # 每次处理前退回仪表盘，避免页面层级混乱
            page.get(panel_url)
            time.sleep(4)

            # 重新抓取元素列表防止 DOM 元素失效 (StaleElementReference)
            current_btns = [el for el in page.eles('tag:button') + page.eles('tag:a') if el.text and 'manage server' in el.text.lower()]
            
            if i >= len(current_btns):
                log(f"{server_name} 管理按钮丢失，跳过", "WARN")
                continue

            try:
                current_btns[i].click()
            except Exception:
                current_btns[i].click(by_js=True)
            
            time.sleep(6) # 等待控制台完全加载

            # 步骤 3: 查找侧边栏的 Renew 按钮
            log(f"查找 {server_name} 的 Renew 按钮...")
            renew_btn = next((el for el in page.eles('tag:button') if el.text and el.text.strip().lower() == 'renew limit reached'), None)
            
            if not renew_btn:
                log(f"{server_name} 未找到 Renew 按钮，可能时间未到或已被风控", "WARN")
                shot = page.get_screenshot(path=f"{screenshot_dir}/{server_name}_no_renew.png")
                send_tg_photo(tg_token, tg_chat_id, shot, f"⚠️ Host-Ship：{server_name} 找不到续期入口")
                continue

            try:
                renew_btn.click()
            except Exception:
                renew_btn.click(by_js=True)
            
            time.sleep(2) # 等待弹窗弹出

            # 步骤 4: 确认弹窗里的 Renew now
            log(f"确认弹窗 Renew now...")
            renew_now_btn = next((el for el in page.eles('tag:button') if el.text and el.text.strip().lower() == 'renew now'), None)
            
            if not renew_now_btn:
                log(f"{server_name} 弹窗加载失败或未找到最终确认按钮", "WARN")
                shot = page.get_screenshot(path=f"{screenshot_dir}/{server_name}_no_renew_now.png")
                send_tg_photo(tg_token, tg_chat_id, shot, f"⚠️ Host-Ship：{server_name} 续期弹窗未正常弹出")
                continue

            try:
                renew_now_btn.click()
            except Exception:
                renew_now_btn.click(by_js=True)

            time.sleep(2) # 给页面反应和渲染警告框的时间

            # ---------------------------------------------------------
            # 检测是否触发 CD 频率限制 (如 "You can renew again in XX seconds.")
            # ---------------------------------------------------------
            alert_el = page.ele('text:You can renew again in')
            if alert_el:
                alert_text = alert_el.text
                match = re.search(r'(\d+)\s*seconds', alert_text, re.IGNORECASE)
                wait_time = int(match.group(1)) + 3 if match else 50 # 提取秒数并多加 3 秒缓冲
                log(f"⚠️ 触发面板 CD 限制: [{alert_text}]，等待 {wait_time} 秒后自动重试...", "WARN")
                time.sleep(wait_time)

                # 重新点击续期确认按钮
                log("CD 结束，再次尝试点击 Renew now...")
                try:
                    renew_now_btn.click()
                except Exception:
                    renew_now_btn.click(by_js=True)
                time.sleep(3)

            log(f"✅ {server_name} 点击续期完成，进行截图备份")
            time.sleep(4)
            shot = page.get_screenshot(path=f"{screenshot_dir}/{server_name}_success.png")
            send_tg_photo(tg_token, tg_chat_id, shot, f"✅ Host-Ship 续订成功\n\n目标：{server_name}\n面板：panel.host-ship.com")
            total_success += 1

            # 如果同一账号下还有后续服务器，主程序等待 60 秒防止触发下一个 CD
            if i < server_count - 1:
                log("等待 60 秒后开始处理同一账号下的下一个服务器...")
                time.sleep(60)

        log(f"任务执行完毕，成功处理 {total_success}/{server_count} 个服务器")

    except Exception as e:
        log(f"执行时发生严重错误: {e}", "ERROR")
        if page:
            err_shot = page.get_screenshot(path=f"{screenshot_dir}/fatal_error.png")
            send_tg_photo(tg_token, tg_chat_id, err_shot, f"❌ Host-Ship 脚本运行崩溃\n\n报错信息:\n{str(e)[:200]}")
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        vdisplay.stop()

if __name__ == "__main__":
    main()
