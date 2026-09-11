```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import requests
from seleniumbase import SB


# ===================== 环境变量 =====================

# Host Ship 登录账号
USERNAME = os.environ.get("HOSTSHIP_USERNAME") or ""
PASSWORD = os.environ.get("HOSTSHIP_PASSWORD") or ""

# Telegram
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""

# Host Ship
BASE_URL = "https://panel.host-ship.com"


# ===================== Telegram 推送 =====================

def send_tg_message(status_icon, status_text, extra=""):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过 Telegram 推送。")
        return

    # UTC + 8
    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    # 用户名脱敏
    if len(USERNAME) > 4:
        masked_username = (
            f"{USERNAME[:2]}****{USERNAME[-2:]}"
        )
    elif len(USERNAME) > 2:
        masked_username = (
            f"{USERNAME[:1]}****{USERNAME[-1:]}"
        )
    else:
        masked_username = USERNAME

    text = (
        f"🚢 Host Ship 续期通知\n\n"
        f"{status_icon} {status_text}\n"
        f"👤 账户: {masked_username}\n"
        f"⏱️ 时间: {current_time_str}"
    )

    if extra:
        text += f"\n📋 详情: {extra}"

    url = (
        f"https://api.telegram.org/"
        f"bot{TG_BOT_TOKEN}/sendMessage"
    )

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text
            },
            timeout=10
        )

        if r.status_code == 200:
            print("📩 Telegram 通知发送成功！")
        else:
            print(f"⚠️ Telegram 通知发送失败: {r.text}")

    except Exception as e:
        print(f"⚠️ Telegram 通知发送异常: {e}")


# ===================== 页面注入脚本 =====================

_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');

    if (!ts) {
        return 'no-turnstile';
    }

    var el = ts;

    for (var i = 0; i < 20; i++) {
        el = el.parentElement;

        if (!el) {
            break;
        }

        var s = window.getComputedStyle(el);

        if (
            s.overflow === 'hidden' ||
            s.overflowX === 'hidden' ||
            s.overflowY === 'hidden'
        ) {
            el.style.overflow = 'visible';
        }

        el.style.minWidth = 'max-content';
    }

    document.querySelectorAll('iframe').forEach(function(f) {
        if (
            f.src &&
            f.src.includes('challenges.cloudflare.com')
        ) {
            f.style.width = '300px';
            f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible';
            f.style.opacity = '1';
        }
    });

    return 'done';
})()
"""


_EXISTS_JS = """
(function() {
    return document.querySelector(
        'input[name="cf-turnstile-response"]'
    ) !== null;
})()
"""


_SOLVED_JS = """
(function() {
    var i = document.querySelector(
        'input[name="cf-turnstile-response"]'
    );

    return !!(
        i &&
        i.value &&
        i.value.length > 20
    );
})()
"""


# ===================== 工具函数 =====================

def js_fill_input(sb, selector: str, text: str):
    """
    使用 JavaScript 原生 setter 填写输入框，
    同时触发 input/change 事件，兼容 React/Vue 等前端框架。
    """

    safe_text = (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    sb.execute_script(
        f"""
        (function() {{
            var el = document.querySelector('{selector}');

            if (!el) {{
                return;
            }}

            var nativeInputValueSetter =
                Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,
                    "value"
                ).set;

            if (nativeInputValueSetter) {{
                nativeInputValueSetter.call(
                    el,
                    "{safe_text}"
                );
            }} else {{
                el.value = "{safe_text}";
            }}

            el.dispatchEvent(
                new Event('input', {{
                    bubbles: true
                }})
            );

            el.dispatchEvent(
                new Event('change', {{
                    bubbles: true
                }})
            );
        }})()
        """
    )


# ===================== Turnstile =====================

def handle_turnstile(sb) -> bool:
    print("🔍 处理 Cloudflare Turnstile 验证...")

    time.sleep(2)

    # 先检查是否已经静默通过
    if sb.execute_script(_SOLVED_JS):
        print("✅ 已静默通过")
        return True

    # 展开 Turnstile iframe / 容器
    for _ in range(3):
        try:
            sb.execute_script(_EXPAND_JS)
        except Exception:
            pass

        time.sleep(0.5)

    # 最多尝试 6 次
    for attempt in range(6):

        # 每次点击前先检查
        if sb.execute_script(_SOLVED_JS):
            print(
                f"✅ Turnstile 通过（第 {attempt} 次尝试）"
            )
            return True

        print(
            f"🖱️ 第 {attempt + 1} 次调用 "
            f"uc_gui_click_captcha..."
        )

        try:
            sb.uc_gui_click_captcha()

        except Exception as e:
            print(
                f"⚠️ uc_gui_click_captcha "
                f"调用异常: {e}"
            )

        # 等待验证结果
        for _ in range(16):

            time.sleep(0.5)

            if sb.execute_script(_SOLVED_JS):
                print(
                    f"✅ Turnstile 通过"
                    f"（第 {attempt + 1} 次尝试）"
                )
                return True

        print(
            f"⚠️ 第 {attempt + 1} 次未通过，重试..."
        )

    print("❌ Turnstile 6 次均失败")
    return False


# ===================== 登录 =====================

def login(sb) -> bool:

    print(
        f"🌐 打开登录页面: "
        f"{BASE_URL}/auth/login"
    )

    sb.uc_open_with_reconnect(
        BASE_URL + "/auth/login",
        reconnect_time=8
    )

    time.sleep(8)

    print("⏳ 等待页面加载 / Cloudflare...")

    cf_passed = False

    for i in range(30):

        page_src = (
            sb.get_page_source() or ""
        ).lower()

        # Username 登录表单
        if (
            'name="username"' in page_src
            or 'id="username"' in page_src
            or 'type="text"' in page_src
            or 'type="password"' in page_src
        ):
            cf_passed = True

            print(
                f"✅ 登录表单已出现（{i + 1}s）"
            )

            break

        time.sleep(1)

    if not cf_passed:
        print(
            "⚠️ 可能仍有 Cloudflare 验证，"
            "继续尝试..."
        )

    # ===================== 等待 Username 输入框 =====================

    username_selector = (
        'input[name="username"], '
        'input#username, '
        'input[type="text"]'
    )

    try:

        sb.wait_for_element(
            username_selector,
            timeout=15
        )

    except Exception:

        print("❌ 页面未加载出 Username 登录表单")

        print(
            f"  当前 URL: "
            f"{sb.get_current_url()}"
        )

        print(
            f"  当前标题: "
            f"{sb.get_title()}"
        )

        sb.save_screenshot(
            "login_load_fail.png"
        )

        return False

    # ===================== Cookie 弹窗 =====================

    try:

        for btn in sb.find_elements("button"):

            txt = (
                btn.text or ""
            ).lower()

            if (
                "accept" in txt
                or "同意" in txt
                or "cookie" in txt
            ):

                btn.click()

                time.sleep(0.5)

                break

    except Exception:
        pass

    # ===================== Username =====================

    print("👤 填写 Username...")

    js_fill_input(
        sb,
        username_selector,
        USERNAME
    )

    time.sleep(1)

    # ===================== Password =====================

    print("🔑 填写密码...")

    js_fill_input(
        sb,
        'input[type="password"], input[name="password"]',
        PASSWORD
    )

    time.sleep(2)

    # ===================== Turnstile =====================

    print("⏳ 等待 Turnstile...")

    ts_found = False

    for i in range(10):

        if sb.execute_script(_EXISTS_JS):

            ts_found = True

            print(
                f"✅ 检测到 Turnstile（{i + 1}s）"
            )

            break

        time.sleep(1)

    if ts_found:

        if not handle_turnstile(sb):

            print(
                "❌ 登录界面的 "
                "Turnstile 验证失败"
            )

            sb.save_screenshot(
                "login_turnstile_fail.png"
            )

            return False

    else:

        print("ℹ️ 未检测到 Turnstile")

    # ===================== 提交登录 =====================

    print("🖱️ 提交登录...")

    try:

        submit = None

        for sel in [
            'button[type="submit"]',
            'button.btn-primary',
            'button'
        ]:

            try:

                btns = sb.find_elements(sel)

                for b in btns:

                    t = (
                        b.text or ""
                    ).lower()

                    if (
                        "login" in t
                        or "sign in" in t
                        or "登录" in t
                        or not t
                    ):

                        submit = b

                        break

                if submit:
                    break

            except Exception:
                continue

        if submit:

            submit.click()

        else:

            sb.press_keys(
                'input[type="password"]',
                '\n'
            )

    except Exception:

        sb.press_keys(
            'input[type="password"]',
            '\n'
        )

    # ===================== 等待登录跳转 =====================

    print("⏳ 等待登录跳转...")

    for _ in range(15):

        time.sleep(1)

        cur = (
            sb.get_current_url()
            .lower()
        )

        title = (
            sb.get_title() or ""
        ).lower()

        if (
            "/auth/login" not in cur
            and (
                "dashboard" in cur
                or "server" in cur
                or "welcome" in title
            )
        ):

            break

    cur = (
        sb.get_current_url()
        .lower()
    )

    if "/auth/login" not in cur:

        print(
            f"✅ 登录成功！"
            f"(URL: {sb.get_current_url()})"
        )

        return True

    print(
        f"❌ 登录失败 "
        f"(URL: {sb.get_current_url()}, "
        f"Title: {sb.get_title()})"
    )

    sb.save_screenshot(
        "login_failed.png"
    )

    return False


# ===================== 进入服务器 =====================

def go_to_server(sb) -> bool:
    """
    从 Dashboard 自动进入第一个服务器管理页
    """

    print("🖥️ 确保在 Dashboard 页面...")

    cur = (
        sb.get_current_url()
        .lower()
    )

    if "/server/" not in cur:

        sb.open(BASE_URL)

        time.sleep(5)

    print(
        "🔍 在 Dashboard 查找服务器并进入管理页..."
    )

    time.sleep(3)

    # ===================== 优先寻找 MANAGE SERVER =====================

    manage_btn = None

    try:

        for el in sb.find_elements(
            "button, a"
        ):

            txt = (
                el.text or ""
            ).strip().upper()

            if (
                "MANAGE SERVER" in txt
                or "管理服务器" in txt
            ):

                manage_btn = el

                print(
                    f"✅ 找到按钮: "
                    f"[{el.text.strip()}]"
                )

                break

    except Exception:
        pass

    if manage_btn:

        try:

            sb.execute_script(
                "arguments[0].scrollIntoView("
                "{block:'center'});",
                manage_btn
            )

            time.sleep(0.5)

            manage_btn.click()

            time.sleep(5)

            print(
                f"📄 已进入服务器页面: "
                f"{sb.get_current_url()}"
            )

            return True

        except Exception as e:

            print(
                f"点击 MANAGE SERVER 失败: {e}"
            )

    # ===================== 备用：寻找 /server/ 链接 =====================

    try:

        for a in sb.find_elements("a"):

            href = (
                a.get_attribute("href")
                or ""
            ).lower()

            if (
                "/server/" in href
                and "create" not in href
            ):

                print(
                    f"✅ 找到服务器链接: {href}"
                )

                a.click()

                time.sleep(5)

                print(
                    f"📄 已进入服务器页面: "
                    f"{sb.get_current_url()}"
                )

                return True

    except Exception as e:

        print(
            f"查找服务器链接异常: {e}"
        )

    # ===================== 再备用：点击服务器名称 =====================

    try:

        for el in sb.find_elements(
            "div, span, h1, h2, h3"
        ):

            txt = (
                el.text or ""
            ).lower()

            if (
                "server" in txt
                and (
                    "online" in txt
                    or "#" in txt
                )
            ):

                el.click()

                time.sleep(5)

                if (
                    "/server/"
                    in sb.get_current_url().lower()
                ):

                    print(
                        f"📄 已进入服务器页面: "
                        f"{sb.get_current_url()}"
                    )

                    return True

    except Exception:
        pass

    print(
        "❌ 未能进入服务器管理页面"
    )

    sb.save_screenshot(
        "go_to_server_fail.png"
    )

    return False


# ===================== 续期流程 =====================

def do_renew(sb):

    print("\n" + "#" * 30)
    print("  开始 Host Ship 续期流程")
    print("#" * 30)

    if not go_to_server(sb):

        send_tg_message(
            "❌",
            "进入服务器页面失败"
        )

        return

    time.sleep(3)

    # ===================== 查找续期按钮 =====================

    print("🔄 查找续期按钮...")

    renew_btn = None
    candidates = []

    try:

        for el in sb.find_elements(
            "button, a, div[role='button']"
        ):

            txt = (
                el.text or ""
            ).strip().lower()

            if not txt:
                continue

            if any(
                k in txt
                for k in [
                    "renew",
                    "续期",
                    "renewal",
                    "extend"
                ]
            ):

                candidates.append(
                    (el, txt)
                )

                print(
                    f"  找到候选按钮: [{txt}]"
                )

    except Exception as e:

        print(
            f"查找按钮异常: {e}"
        )

    # ===================== 判断续期状态 =====================

    for el, txt in candidates:

        if (
            "limit reached" in txt
            or "已达上限" in txt
            or "无法续期" in txt
        ):

            print(
                f"ℹ️ 当前显示「{txt}」，"
                f"可能未到续期窗口"
            )

            send_tg_message(
                "⏳",
                "未到续期时间 / 已达上限",
                txt
            )

            sb.save_screenshot(
                "renew_limit.png"
            )

            return

        if (
            "renew" in txt
            or "续期" in txt
        ):

            renew_btn = el

            break

    if not renew_btn and candidates:

        renew_btn = candidates[0][0]

    if not renew_btn:

        print(
            "❌ 未找到任何续期相关按钮"
        )

        try:

            page = (
                sb.get_page_source()
                or ""
            )

            if (
                "renewal" in page.lower()
                or "renew" in page.lower()
            ):

                print(
                    "页面源码中包含 renew "
                    "关键字，可能是按钮文本变化"
                )

        except Exception:
            pass

        sb.save_screenshot(
            "no_renew_btn.png"
        )

        send_tg_message(
            "❌",
            "未找到续期按钮"
        )

        return

    print(
        f"🖱️ 点击续期按钮: "
        f"{(renew_btn.text or '').strip()}"
    )

    try:

        sb.execute_script(
            "arguments[0].scrollIntoView("
            "{block:'center'});",
            renew_btn
        )

        time.sleep(0.5)

        renew_btn.click()

    except Exception:

        sb.execute_script(
            "arguments[0].click();",
            renew_btn
        )

    time.sleep(5)

    # ===================== 确认弹窗 =====================

    print(
        "⏳ 检查是否有确认弹窗或验证..."
    )

    try:

        for btn in sb.find_elements("button"):

            t = (
                btn.text or ""
            ).lower()

            if any(
                k in t
                for k in [
                    "confirm",
                    "yes",
                    "ok",
                    "renew",
                    "确认",
                    "续期"
                ]
            ):

                print(
                    f"🖱️ 点击确认: "
                    f"{btn.text}"
                )

                btn.click()

                time.sleep(3)

                break

    except Exception:
        pass

    # ===================== 再次检查 Turnstile =====================

    if sb.execute_script(_EXISTS_JS):

        print(
            "检测到续期页 Turnstile，"
            "尝试处理..."
        )

        handle_turnstile(sb)

        time.sleep(2)

        try:

            for btn in sb.find_elements(
                "button"
            ):

                if (
                    "renew"
                    in (btn.text or "").lower()
                ):

                    btn.click()

                    break

        except Exception:
            pass

    time.sleep(6)

    # ===================== 结果判断 =====================

    page = (
        sb.get_page_source()
        or ""
    ).lower()

    cur_url = (
        sb.get_current_url()
    )

    if any(
        k in page
        for k in [
            "success",
            "renewed",
            "extended",
            "成功",
            "已续期"
        ]
    ):

        print("✅ 续期成功！")

        send_tg_message(
            "✅",
            "续期成功"
        )

    elif (
        "limit reached" in page
        or "无法续期" in page
        or "not eligible" in page
    ):

        print(
            "⏳ 未到续期窗口或已达上限"
        )

        send_tg_message(
            "⏳",
            "未到续期时间 / 已达上限"
        )

    else:

        print(
            "ℹ️ 续期操作已执行，"
            "请人工确认结果"
        )

        send_tg_message(
            "ℹ️",
            "续期操作已执行，请人工确认",
            cur_url
        )

    sb.save_screenshot(
        "renew_result.png"
    )


# ===================== 主入口 =====================

def main():

    print("#" * 30)
    print("   Host Ship 自动登录续期")
    print("#" * 30)

    # ===================== 检查账号 =====================

    if not USERNAME or not PASSWORD:

        print(
            "❌ 请设置 "
            "HOSTSHIP_USERNAME 和 "
            "HOSTSHIP_PASSWORD"
        )

        return

    # ===================== 代理配置 =====================

    IS_PROXY = (
        os.environ.get(
            "IS_PROXY",
            "false"
        ).lower()
        == "true"
    )

    proxy_str = (
        os.environ.get(
            "PROXY_SERVER",
            ""
        ).strip()
        or "http://127.0.0.1:1081"
    )

    sb_kwargs = {
        "uc": True,
        "headless": False
    }

    if IS_PROXY:

        print(
            f"🔗 使用代理: {proxy_str}"
        )

        sb_kwargs["proxy"] = proxy_str

    else:

        print("🌐 直连访问")

    # ===================== 启动浏览器 =====================

    print("🚀 启动浏览器...")

    with SB(**sb_kwargs) as sb:

        # ===================== 测试出口 IP =====================

        try:

            sb.open(
                "https://api.ip.sb/ip"
            )

            print(
                f"📍 当前出口IP: "
                f"{sb.get_text('body')}"
            )

        except Exception:
            pass

        # ===================== 登录 + 续期 =====================

        if login(sb):

            do_renew(sb)

        else:

            print(
                "\n❌ 登录失败，终止续期。"
            )

            send_tg_message(
                "❌",
                "登录失败"
            )


# ===================== 程序入口 =====================

if __name__ == "__main__":
    main()
```
